"""Applications core (ADR 010): one object for sign-on, assignments and provisioning."""

import pytest

from backend.app.applications.models import Application, ApplicationAssignment
from backend.app.audit.model import AuditEvent
from tests.conftest import Api, make_user
from tests.recipe_helpers import new_group, new_user, rkey  # noqa: F401
from tests.test_oidc_authorize import CB, authorize, loc, mk, params

from tests.test_provisioning import make_app


def mkapp(sa, **over):
    r = sa.post("/admin/applications", {"name": "Wiki", "sign_on_mode": "bookmark", "launch_url": "https://wiki.example.com/", **over})
    assert r.status_code == 201, r.text
    return r.json()


def assign(sa, app, **who):
    r = sa.post(f"/admin/applications/{app['id']}/assignments", who)
    assert r.status_code == 201, r.text
    return r.json()


def actions(db, name):
    db.expire_all()
    return [e for e in db.query(AuditEvent).all() if str(getattr(e.action, "value", e.action)) == name]


def test_crud_and_validation(super_admin):
    a = mkapp(super_admin)
    assert a["sign_on_mode"] == "bookmark" and a["require_assignment"] is True and a["provisioning"] is None and a["oidc_client"] is None
    assert super_admin.post("/admin/applications", {"name": "Wiki", "sign_on_mode": "none"}).status_code == 409          # unique name
    assert super_admin.post("/admin/applications", {"name": "B", "sign_on_mode": "bookmark"}).status_code == 422          # needs URL
    for bad in ("javascript:alert(1)", "ftp://x.example.com", "https://u:p@x.example.com/", "//x.example.com"):
        assert super_admin.post("/admin/applications", {"name": "B", "sign_on_mode": "bookmark", "launch_url": bad}).status_code == 422, bad
    assert super_admin.post("/admin/applications", {"name": "B", "sign_on_mode": "swa"}).status_code == 422
    r = super_admin.put(f"/admin/applications/{a['id']}", {"name": "Wiki 2", "sign_on_mode": "bookmark", "launch_url": "https://wiki2.example.com/"})
    assert r.status_code == 200 and r.json()["name"] == "Wiki 2"
    assert [x["name"] for x in super_admin.get("/admin/applications?q=wiki").json()["items"]] == ["Wiki 2"]
    assert super_admin.delete(f"/admin/applications/{a['id']}").status_code == 200
    assert super_admin.get(f"/admin/applications/{a['id']}").status_code == 404


def test_members_cannot_use_the_admin_api(super_admin, member):
    a = mkapp(super_admin)
    assert member.get("/admin/applications").status_code == 403
    assert member.post("/admin/applications", {"name": "X", "sign_on_mode": "none"}).status_code == 403
    assert member.post(f"/admin/applications/{a['id']}/assignments", {"user_id": member.user.id}).status_code == 403


def test_assignment_rules(db, super_admin, member):
    a = mkapp(super_admin)
    g = new_group(super_admin, "Staff")
    assert super_admin.post(f"/admin/applications/{a['id']}/assignments", {}).status_code == 422
    assert super_admin.post(f"/admin/applications/{a['id']}/assignments", {"user_id": member.user.id, "group_id": g}).status_code == 422
    assert super_admin.post(f"/admin/applications/{a['id']}/assignments", {"user_id": 99999}).status_code == 404
    x = assign(super_admin, a, user_id=member.user.id)
    assert super_admin.post(f"/admin/applications/{a['id']}/assignments", {"user_id": member.user.id}).status_code == 409
    assign(super_admin, a, group_id=g)
    assert len(super_admin.get(f"/admin/applications/{a['id']}/assignments").json()["items"]) == 2
    assert super_admin.delete(f"/admin/applications/{a['id']}/assignments/{x['id']}").status_code == 200
    assert super_admin.delete(f"/admin/applications/{a['id']}/assignments/{x['id']}").status_code == 404
    assert len(actions(db, "APPLICATION_ASSIGNMENT_ADDED")) == 2


def test_my_apps_shows_only_entitled_active_visible(db, super_admin, member):
    wiki = mkapp(super_admin)
    hidden = mkapp(super_admin, name="Hidden", visible=False)
    off = mkapp(super_admin, name="Off", status="inactive")
    mkapp(super_admin, name="Other")                           # never assigned
    mkapp(super_admin, name="Open", require_assignment=False)   # sign-in is open to all, but a tile only appears when assigned
    for a in (wiki, hidden, off):
        assign(super_admin, a, user_id=member.user.id)
    names = [x["name"] for x in member.get("/me/apps").json()["items"]]
    assert names == ["Wiki"], names                            # hidden, inactive and unassigned apps are not listed


def test_group_assignment_follows_membership_and_active_status(db, super_admin, member):
    a = mkapp(super_admin)
    g = new_group(super_admin, "Staff")
    assign(super_admin, a, group_id=g)
    assert member.get("/me/apps").json()["items"] == []
    assert super_admin.post(f"/admin/groups/{g}/members", {"user_id": member.user.id}).status_code in (200, 201)
    assert [x["name"] for x in member.get("/me/apps").json()["items"]] == ["Wiki"]
    assert super_admin.delete(f"/admin/groups/{g}/members/{member.user.id}").status_code == 200
    assert member.get("/me/apps").json()["items"] == []


def test_launch_returns_url_audits_and_hides_unassigned(db, super_admin, member):
    a = mkapp(super_admin)
    r = member.post(f"/me/apps/{a['id']}/launch")
    assert r.status_code == 404                               # not assigned: same answer as for a missing app
    assert member.post("/me/apps/99999/launch").status_code == 404
    assign(super_admin, a, user_id=member.user.id)
    r = member.post(f"/me/apps/{a['id']}/launch")
    assert r.status_code == 200 and r.json() == {"url": "https://wiki.example.com/"}
    assert len(actions(db, "APPLICATION_LAUNCHED")) == 1
    super_admin.put(f"/admin/applications/{a['id']}", {"name": "Wiki", "sign_on_mode": "bookmark", "launch_url": "https://wiki.example.com/", "status": "inactive"})
    assert member.post(f"/me/apps/{a['id']}/launch").status_code == 404
    assert Api().get("/me/apps").status_code == 401


def test_provisioning_app_shares_the_application_and_its_assignments(db, super_admin, member, rkey):
    p = make_app(super_admin, name="Acme")
    assert p["application_id"]
    a = super_admin.get(f"/admin/applications/{p['application_id']}").json()
    assert a["sign_on_mode"] == "none" and a["provisioning"]["id"] == p["id"] and a["visible"] is False
    assign(super_admin, a, user_id=member.user.id)
    items = super_admin.get(f"/admin/provisioning-apps/{p['id']}/assignments").json()["items"]
    assert [i["subject_id"] for i in items] == [member.user.id]  # one list, two views
    assert member.get("/me/apps").json()["items"] == []        # sign-on none: nothing to launch
    assert super_admin.delete(f"/admin/applications/{a['id']}").status_code == 409   # provisioning still attached
    assert super_admin.delete(f"/admin/provisioning-apps/{p['id']}").status_code == 200
    assert super_admin.get(f"/admin/applications/{a['id']}").status_code == 404


def test_creating_an_oidc_client_creates_an_application_and_deleting_removes_it(db, super_admin):
    c = mk(super_admin)
    items = super_admin.get("/admin/applications").json()["items"]
    assert len(items) == 1 and items[0]["sign_on_mode"] == "oidc" and items[0]["oidc_client"]["client_id"] == c["client_id"]
    assert items[0]["require_assignment"] is False                       # compatibility: nobody is locked out by upgrading
    assert super_admin.delete(f"/admin/oidc/clients/{c['id']}").status_code == 200
    assert super_admin.get("/admin/applications").json()["items"] == []


def test_service_clients_are_not_shown_to_users(db, super_admin):
    r = super_admin.post("/admin/oidc/clients", {"name": "Svc", "client_type": "service", "redirect_uris": [], "allowed_scopes": ["x"], "allowed_audiences": ["https://api.example.com"]})
    if r.status_code == 201:
        assert super_admin.get("/admin/applications").json()["items"][0]["visible"] is False


def test_authorize_is_denied_when_assignment_is_required(db, super_admin, member):
    c = mk(super_admin)
    app_id = super_admin.get("/admin/applications").json()["items"][0]["id"]
    # not required: works as before
    assert "request_id" in loc(authorize(member, params(c)))[1]
    cur = super_admin.get(f"/admin/applications/{app_id}").json()
    r = super_admin.put(f"/admin/applications/{app_id}", {"name": cur["name"], "sign_on_mode": "oidc", "require_assignment": True})
    assert r.status_code == 200, r.text
    q = loc(authorize(member, params(c)))[1]
    assert q.get("error") == "access_denied" and "request_id" not in q
    assign(super_admin, {"id": app_id}, user_id=member.user.id)
    assert "request_id" in loc(authorize(member, params(c)))[1]


def test_inactive_application_blocks_oidc_sign_in_for_everyone(db, super_admin, member):
    c = mk(super_admin)
    app_id = super_admin.get("/admin/applications").json()["items"][0]["id"]
    cur = super_admin.get(f"/admin/applications/{app_id}").json()
    assert super_admin.put(f"/admin/applications/{app_id}", {"name": cur["name"], "sign_on_mode": "oidc", "status": "inactive", "require_assignment": False}).status_code == 200
    assert loc(authorize(member, params(c)))[1].get("error") == "access_denied"


def test_attach_and_detach_oidc_client(db, super_admin):
    c = mk(super_admin)
    other = mkapp(super_admin, name="Plain", sign_on_mode="none", launch_url=None)
    # attaching a client that already has an application is refused
    r = super_admin.post(f"/admin/applications/{other['id']}/oidc-client", {"client_pk": c["id"]})
    assert r.status_code == 409, r.text                                   # sign-on mode must be OIDC first
    super_admin.put(f"/admin/applications/{other['id']}", {"name": "Plain", "sign_on_mode": "oidc"})
    assert super_admin.post(f"/admin/applications/{other['id']}/oidc-client", {"client_pk": c["id"]}).status_code == 409   # belongs to another app
    own = super_admin.get("/admin/applications?q=Demo").json()["items"][0]
    assert super_admin.delete(f"/admin/applications/{own['id']}/oidc-client").status_code == 200
    assert super_admin.get(f"/admin/applications/{own['id']}").json()["oidc_client"] is None
    r = super_admin.post(f"/admin/applications/{other['id']}/oidc-client", {"client_pk": c["id"]})
    assert r.status_code == 200 and r.json()["oidc_client"]["client_id"] == c["client_id"]
    assert len(actions(db, "APPLICATION_OIDC_ATTACHED")) == 1 and len(actions(db, "APPLICATION_OIDC_DETACHED")) == 1


# ---- icons ---------------------------------------------------------------------------------------------------

import base64

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 32
b64 = lambda raw: base64.b64encode(raw).decode()  # noqa: E731


def test_icon_upload_validation(super_admin):
    a = mkapp(super_admin)
    for raw in (PNG, JPEG, WEBP):
        assert super_admin.put(f"/admin/applications/{a['id']}/icon", {"data": b64(raw)}).status_code == 200
    assert super_admin.put(f"/admin/applications/{a['id']}/icon", {"data": b64(b"<svg onload=alert(1)/>")}).status_code == 422   # no SVG
    assert super_admin.put(f"/admin/applications/{a['id']}/icon", {"data": b64(b"GIF89a" + b"0" * 20)}).status_code == 422
    assert super_admin.put(f"/admin/applications/{a['id']}/icon", {"data": "not base64!!"}).status_code == 422
    assert super_admin.put(f"/admin/applications/{a['id']}/icon", {"data": b64(PNG + b"0" * 103_000)}).status_code == 422          # too big
    r = super_admin.get(f"/admin/applications/{a['id']}/icon")
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp" and r.headers["x-content-type-options"] == "nosniff"
    assert super_admin.get(f"/admin/applications/{a['id']}").json()["has_icon"] is True
    assert super_admin.delete(f"/admin/applications/{a['id']}/icon").status_code == 200
    assert super_admin.get(f"/admin/applications/{a['id']}/icon").status_code == 404


def test_icon_is_served_only_to_entitled_users(db, super_admin, member):
    a = mkapp(super_admin)
    super_admin.put(f"/admin/applications/{a['id']}/icon", {"data": b64(PNG)})
    assert member.get(f"/me/apps/{a['id']}/icon").status_code == 404
    assign(super_admin, a, user_id=member.user.id)
    r = member.get(f"/me/apps/{a['id']}/icon")
    assert r.status_code == 200 and r.content == PNG and r.headers["content-security-policy"] == "default-src 'none'"
    assert member.get("/me/apps").json()["items"][0]["has_icon"] is True
    assert member.put(f"/admin/applications/{a['id']}/icon", {"data": b64(PNG)}).status_code == 403
    assert Api().get(f"/me/apps/{a['id']}/icon").status_code == 401


# ---- OIDC templates and IdP-initiated launch -----------------------------------------------------------------

def test_templates_listed_and_unknown_rejected(super_admin):
    ids = [t["id"] for t in super_admin.get("/admin/applications/templates").json()["items"]]
    assert ids == ["web", "spa", "native", "service"]
    assert super_admin.post("/admin/applications/from-template", {"template": "nope", "name": "X"}).status_code == 422


def test_web_template_creates_app_and_client_with_secret_and_requires_assignment(super_admin, member):
    r = super_admin.post("/admin/applications/from-template", {"template": "web", "name": "Portal", "redirect_uris": ["https://portal.example.com/cb"],
                                                              "launch_url": "https://portal.example.com/"})
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["client_type"] == "confidential" and c["client_secret"].startswith("idf_cs_")
    a = super_admin.get(f"/admin/applications/{c['application_id']}").json()
    assert a["sign_on_mode"] == "oidc" and a["require_assignment"] is True and a["launch_url"] == "https://portal.example.com/" and a["visible"] is True
    # secure default: unassigned user is refused until assigned
    p = {"client_id": c["client_id"], "redirect_uri": "https://portal.example.com/cb", "response_type": "code", "scope": "openid",
         "code_challenge": "x" * 43, "code_challenge_method": "S256", "state": "s"}
    assert loc(member.c.get("/oauth/authorize", params=p, follow_redirects=False))[1].get("error") == "access_denied"
    assign(super_admin, a, user_id=member.user.id)
    assert "request_id" in loc(member.c.get("/oauth/authorize", params=p, follow_redirects=False))[1]


def test_spa_and_native_templates_are_public_without_secret(super_admin):
    for tpl, uri in (("spa", "https://spa.example.com/cb"), ("native", "http://127.0.0.1:8123/cb")):
        r = super_admin.post("/admin/applications/from-template", {"template": tpl, "name": tpl, "redirect_uris": [uri]})
        assert r.status_code == 201, r.text
        assert r.json()["client_type"] == "public" and "client_secret" not in r.json()
    bad = super_admin.post("/admin/applications/from-template", {"template": "native", "name": "n2", "redirect_uris": ["myapp://cb"]})
    assert bad.status_code == 422                                    # custom schemes are not supported (documented)
    assert super_admin.post("/admin/applications/from-template", {"template": "spa", "name": "spa"}).status_code == 409   # name taken
    assert super_admin.post("/admin/applications/from-template", {"template": "spa", "name": "s3"}).status_code == 422     # redirect required


def test_service_template_needs_super_admin_and_is_not_a_tile(super_admin, admin):
    body = {"template": "service", "name": "Sync job", "allowed_audiences": ["https://api.example.com"]}
    assert admin.post("/admin/applications/from-template", body).status_code == 403
    r = super_admin.post("/admin/applications/from-template", body)
    assert r.status_code == 201, r.text
    a = super_admin.get(f"/admin/applications/{r.json()['application_id']}").json()
    assert a["visible"] is False and a["launch_url"] is None


def test_failed_template_creates_nothing(super_admin):
    assert super_admin.post("/admin/applications/from-template", {"template": "web", "name": "Half", "redirect_uris": ["http://evil.example.com/cb"]}).status_code == 422
    assert super_admin.get("/admin/applications").json()["items"] == []


def test_idp_initiated_launch_sends_iss_and_target_link_uri(db, super_admin, member):
    from urllib.parse import parse_qs, urlsplit
    from backend.app.config import settings

    r = super_admin.post("/admin/applications/from-template", {"template": "web", "name": "Portal", "redirect_uris": ["https://portal.example.com/cb"],
                                                              "launch_url": "https://portal.example.com/home", "initiate_login_uri": "https://portal.example.com/login"})
    assert r.status_code == 201, r.text
    app_id = r.json()["application_id"]
    assign(super_admin, {"id": app_id}, user_id=member.user.id)
    url = member.post(f"/me/apps/{app_id}/launch").json()["url"]
    u = urlsplit(url)
    assert f"{u.scheme}://{u.netloc}{u.path}" == "https://portal.example.com/login"
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    assert q == {"iss": settings.OIDC_ISSUER, "target_link_uri": "https://portal.example.com/home"}
    # only initiate URI, no home page: still launchable
    super_admin.put(f"/admin/applications/{app_id}", {"name": "Portal", "sign_on_mode": "oidc", "launch_url": ""})
    assert member.get("/me/apps").json()["items"][0]["launchable"] is True
    assert "target_link_uri" not in member.post(f"/me/apps/{app_id}/launch").json()["url"]


def test_initiate_login_uri_validation_and_update(super_admin):
    c = mk(super_admin)
    for bad in ("http://evil.example.com/login", "javascript:alert(1)", "https://x.example.com/a#f", "https://u:p@x.example.com/"):
        assert super_admin.patch(f"/admin/oidc/clients/{c['id']}", {"initiate_login_uri": bad}).status_code == 422, bad
    r = super_admin.patch(f"/admin/oidc/clients/{c['id']}", {"initiate_login_uri": "https://x.example.com/login"})
    assert r.status_code == 200 and r.json()["initiate_login_uri"] == "https://x.example.com/login"
    assert super_admin.patch(f"/admin/oidc/clients/{c['id']}", {"initiate_login_uri": ""}).json()["initiate_login_uri"] is None
