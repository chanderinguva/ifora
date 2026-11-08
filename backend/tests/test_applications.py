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
    assert super_admin.post("/admin/applications", {"name": "B", "sign_on_mode": "saml"}).status_code == 422
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
