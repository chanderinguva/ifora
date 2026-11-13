"""M7: service (client_credentials) clients and RFC 7662 introspection."""

import base64
from urllib.parse import quote

import pytest

from backend.app.audit.model import AuditEvent
from backend.app.config import settings
from backend.app.oidc import keys
from tests.test_oidc_authorize import CB, authorize, params
from tests.test_oidc_refresh import refresh, start
from tests.test_oidc_token import exchange, get_code, mk as mk_user_client, post_token, user_api  # noqa: F401 (fixture)

API = "https://api.example.com"
API2 = "https://reports.example.com"


def mk_service(super_admin, **kw):
    body = {"name": "Billing job", "client_type": "service", "allowed_scopes": ["invoices:read", "invoices:write"],
            "allowed_audiences": [API], **kw}
    r = super_admin.post("/admin/oidc/clients", body)
    assert r.status_code == 201, r.text
    return r.json()


def basic(c, secret=None):
    cred = f"{quote(c['client_id'], safe='')}:{quote(secret or c['client_secret'], safe='')}"
    return {"Authorization": "Basic " + base64.b64encode(cred.encode()).decode()}


def cc(api, c, headers=None, **data):
    return post_token(api, {"grant_type": "client_credentials", **data}, headers or basic(c))


def intro(api, caller, token, **extra):
    return api.c.post("/oauth/introspect", data={"token": token, **extra}, headers=basic(caller))


# ---- registration ---------------------------------------------------------------------------------------

def test_service_client_registration(super_admin):
    c = mk_service(super_admin)
    assert c["client_type"] == "service" and c["grant_types"] == ["client_credentials"]
    assert c["redirect_uris"] == [] and c["allowed_audiences"] == [API]
    assert c["client_secret"].startswith("idf_cs_") and c["token_endpoint_auth_method"] == "client_secret_basic"


@pytest.mark.parametrize("over,msg", [
    ({"allowed_scopes": ["openid"]}, "identity scope"),
    ({"allowed_scopes": ["email"]}, "identity scope"),
    ({"allowed_scopes": ["Bad Scope"]}, "invalid scope"),
    ({"allowed_scopes": []}, "at least one scope"),
    ({"allowed_scopes": ["a", "a"]}, "duplicate"),
    ({"allowed_audiences": []}, "at least one audience"),
    ({"allowed_audiences": ["http://api.example.com"]}, "https"),
    ({"allowed_audiences": ["https://api.example.com/*"]}, "wildcard"),
    ({"redirect_uris": [CB]}, "no redirect"),
    ({"first_party": True}, "first-party"),
])
def test_service_client_validation(super_admin, over, msg):
    r = super_admin.post("/admin/oidc/clients", {"name": "x", "client_type": "service", "allowed_scopes": ["a:b"],
                                                 "allowed_audiences": [API], **over})
    assert r.status_code == 422 and msg in r.json()["detail"], r.text


def test_only_a_super_admin_creates_service_clients(admin):
    r = admin.post("/admin/oidc/clients", {"name": "x", "client_type": "service", "allowed_scopes": ["a:b"], "allowed_audiences": [API]})
    assert r.status_code == 403


def test_audiences_only_for_service_clients(super_admin):
    r = super_admin.post("/admin/oidc/clients", {"name": "x", "redirect_uris": [CB], "allowed_audiences": [API]})
    assert r.status_code == 422


def test_service_client_can_be_updated_and_rotated(super_admin):
    c = mk_service(super_admin)
    r = super_admin.patch(f"/admin/oidc/clients/{c['id']}", {"allowed_scopes": ["invoices:read"], "allowed_audiences": [API, API2]})
    assert r.status_code == 200 and r.json()["allowed_scopes"] == ["invoices:read"] and r.json()["allowed_audiences"] == [API, API2]
    assert super_admin.patch(f"/admin/oidc/clients/{c['id']}", {"allowed_scopes": ["openid"]}).status_code == 422
    assert super_admin.post(f"/admin/oidc/clients/{c['id']}/secrets", {}).status_code == 201


# ---- client credentials grant ---------------------------------------------------------------------------

def test_client_credentials_issues_an_access_token_only(db, super_admin, user_api):
    c = mk_service(super_admin)
    r = cc(user_api, c, scope="invoices:read")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"access_token", "token_type", "expires_in", "scope"}     # no id_token, no refresh_token
    assert body["scope"] == "invoices:read" and r.headers["cache-control"] == "no-store"
    claims = keys.verify_jwt(db, body["access_token"], issuer=settings.OIDC_ISSUER, audience=API, typ="at+jwt")
    assert claims["sub"] == c["client_id"] == claims["client_id"] and claims["scope"] == "invoices:read"
    assert "auth_time" not in claims
    assert db.query(AuditEvent).filter(AuditEvent.action == "OIDC_TOKEN_ISSUED").count() >= 1


def test_defaults_to_all_allowed_scopes_and_the_only_audience(db, super_admin, user_api):
    c = mk_service(super_admin)
    body = cc(user_api, c).json()
    assert body["scope"] == "invoices:read invoices:write"
    assert keys.verify_jwt(db, body["access_token"], issuer=settings.OIDC_ISSUER, audience=API)


@pytest.mark.parametrize("data", [{"scope": "invoices:admin"}, {"scope": "invoices:read invoices:read"}, {"scope": "openid"}])
def test_scope_outside_the_allow_list(super_admin, user_api, data):
    r = cc(user_api, mk_service(super_admin), **data)
    assert r.status_code == 400 and r.json()["error"] == "invalid_scope"


def test_resource_selection(db, super_admin, user_api):
    c = mk_service(super_admin, allowed_audiences=[API, API2])
    assert cc(user_api, c).json()["error"] == "invalid_target"                      # two audiences: must choose
    assert cc(user_api, c, resource="https://evil.example.com").json()["error"] == "invalid_target"
    ok = cc(user_api, c, resource=API2).json()
    assert keys.verify_jwt(db, ok["access_token"], issuer=settings.OIDC_ISSUER, audience=API2)
    with pytest.raises(keys.TokenError):                                           # not valid for the other resource
        keys.verify_jwt(db, ok["access_token"], issuer=settings.OIDC_ISSUER, audience=API)


def test_authentication_is_required(super_admin, user_api):
    c = mk_service(super_admin)
    assert post_token(user_api, {"grant_type": "client_credentials"}).status_code == 401
    bad = cc(user_api, c, headers=basic(c, "idf_cs_wrong"))
    assert bad.status_code == 401 and bad.json()["error"] == "invalid_client"
    assert post_token(user_api, {"grant_type": "client_credentials", "client_id": c["client_id"]}).status_code == 401  # no secret-less service clients


def test_disabled_service_client_gets_nothing(super_admin, user_api):
    c = mk_service(super_admin)
    assert super_admin.patch(f"/admin/oidc/clients/{c['id']}", {"status": "disabled"}).status_code == 200
    assert cc(user_api, c).status_code == 401


def test_other_client_types_cannot_use_the_grant(super_admin, user_api):
    conf = mk_user_client(super_admin, client_type="confidential")
    r = post_token(user_api, {"grant_type": "client_credentials"}, basic(conf))
    assert r.status_code == 400 and r.json()["error"] == "unauthorized_client"
    pub = mk_user_client(super_admin)
    r = post_token(user_api, {"grant_type": "client_credentials", "client_id": pub["client_id"]})
    assert r.status_code == 400 and r.json()["error"] == "unauthorized_client"


def test_service_client_cannot_run_user_flows(super_admin, user_api):
    c = mk_service(super_admin)
    r = authorize(user_api, params(c))                                              # no redirect URIs, wrong grant
    assert r.status_code == 400
    for g in ({"grant_type": "authorization_code", "code": "x", "redirect_uri": CB, "code_verifier": "v" * 50},
              {"grant_type": "refresh_token", "refresh_token": "x"}):
        r = post_token(user_api, g, basic(c))
        assert r.status_code == 400 and r.json()["error"] == "unauthorized_client"


def test_a_service_token_is_not_accepted_by_userinfo(super_admin, user_api):
    c = mk_service(super_admin)
    t = cc(user_api, c).json()["access_token"]
    r = user_api.c.get("/oauth/userinfo", headers={"Authorization": f"Bearer {t}"})
    assert r.status_code in (401, 403)


def test_discovery_lists_the_grant_and_introspection():
    from fastapi.testclient import TestClient
    from backend.app.main import app
    d = TestClient(app).get("/.well-known/openid-configuration").json()
    assert "client_credentials" in d["grant_types_supported"] and d["introspection_endpoint"].endswith("/oauth/introspect")


# ---- introspection --------------------------------------------------------------------------------------

def test_introspection_of_a_service_token(super_admin, user_api):
    c = mk_service(super_admin)
    t = cc(user_api, c, scope="invoices:read").json()["access_token"]
    r = intro(user_api, c, t)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    b = r.json()
    assert b["active"] is True and b["scope"] == "invoices:read" and b["client_id"] == c["client_id"] and b["aud"] == API
    assert b["token_type"] == "Bearer" and b["sub"] == c["client_id"] and "exp" in b and "jti" in b


def test_a_resource_server_can_introspect_tokens_for_its_audience_and_nobody_else_can(super_admin, user_api):
    caller = mk_service(super_admin, name="client")
    rs = mk_service(super_admin, name="API server", allowed_scopes=["x:y"], allowed_audiences=[API])   # its audience includes API
    other = mk_service(super_admin, name="stranger", allowed_scopes=["x:y"], allowed_audiences=[API2])
    t = cc(user_api, caller).json()["access_token"]
    assert intro(user_api, rs, t).json()["active"] is True
    assert intro(user_api, other, t).json() == {"active": False}


@pytest.mark.parametrize("token", ["", "garbage", "a.b.c", "idf_rt_nope"])
def test_unknown_tokens_are_just_inactive(super_admin, user_api, token):
    c = mk_service(super_admin)
    r = intro(user_api, c, token or "x")
    assert r.status_code == 200 and r.json() == {"active": False}


def test_introspection_requires_a_confidential_or_service_caller(super_admin, user_api):
    c = mk_service(super_admin)
    t = cc(user_api, c).json()["access_token"]
    assert user_api.c.post("/oauth/introspect", data={"token": t}).status_code == 401
    assert intro(user_api, c, t).status_code == 200
    pub = mk_user_client(super_admin)
    assert user_api.c.post("/oauth/introspect", data={"token": t, "client_id": pub["client_id"]}).status_code == 401
    bad = user_api.c.post("/oauth/introspect", data={"token": t}, headers=basic(c, "idf_cs_wrong"))
    assert bad.status_code == 401


def test_a_disabled_issuer_makes_its_tokens_inactive_at_once(super_admin, user_api):
    c = mk_service(super_admin)
    rs = mk_service(super_admin, name="rs", allowed_scopes=["x:y"])
    t = cc(user_api, c).json()["access_token"]
    assert intro(user_api, rs, t).json()["active"] is True
    super_admin.patch(f"/admin/oidc/clients/{c['id']}", {"status": "disabled"})
    assert intro(user_api, rs, t).json() == {"active": False}


def test_user_access_token_introspection_follows_the_user(db, super_admin, user_api):
    c = mk_user_client(super_admin, client_type="confidential")
    tok = exchange(user_api, c, get_code(user_api, c)).json()
    r = intro(user_api, c, tok["access_token"])
    b = r.json()
    assert b["active"] is True and b["sub"] == user_api.user.public_id and b["scope"] == "openid profile email"
    assert "email" not in b                                                         # no profile data through introspection
    user_api.user.status = "inactive"
    db.commit()
    assert intro(user_api, c, tok["access_token"]).json() == {"active": False}


def test_refresh_token_introspection(super_admin, user_api):
    c, tok = start(super_admin, user_api, client_type="confidential")
    old = tok["refresh_token"]
    b = intro(user_api, c, old, token_type_hint="refresh_token").json()
    assert b["active"] is True and b["token_type"] == "refresh_token" and "offline_access" in b["scope"]
    new = refresh(user_api, c, old).json()["refresh_token"]
    assert intro(user_api, c, old).json() == {"active": False}                      # rotated away
    assert intro(user_api, c, new).json()["active"] is True
    other = mk_service(super_admin)
    assert intro(user_api, other, new).json() == {"active": False}                  # someone else's refresh token
