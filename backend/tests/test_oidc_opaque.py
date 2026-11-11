"""Opaque access tokens (per-client format), their revocation, and CORS on /oauth/revoke."""

from backend.app.oidc.models import AccessToken
from tests.test_oidc_refresh import revoke, start
from tests.test_oidc_service_clients import API, cc, intro, mk_service
from tests.test_oidc_token import CB, user_api  # noqa: F401 (fixture)


def bearer(t):
    return {"Authorization": f"Bearer {t}"}


def test_client_credentials_opaque_token(db, super_admin, user_api):
    c = mk_service(super_admin, access_token_format="opaque")
    assert c["access_token_format"] == "opaque"
    r = cc(user_api, c)
    assert r.status_code == 200
    tok = r.json()["access_token"]
    assert tok.startswith("idf_at_") and tok.count(".") == 0
    row = db.query(AccessToken).one()
    assert row.token_hash != tok and len(row.token_hash) == 64 and row.user_id is None and row.audience == API
    i = intro(user_api, c, tok).json()
    assert i["active"] is True and i["aud"] == API and i["client_id"] == c["client_id"] and i["scope"] == "invoices:read invoices:write"
    assert revoke(user_api, c, tok).status_code == 200
    assert intro(user_api, c, tok).json() == {"active": False}


def test_opaque_tokens_are_private_to_their_owner_and_audience(db, super_admin, user_api):
    a = mk_service(super_admin, access_token_format="opaque")
    b = mk_service(super_admin, name="Other job", allowed_audiences=["https://other.example.com"])
    tok = cc(user_api, a).json()["access_token"]
    assert intro(user_api, b, tok).json() == {"active": False}                 # not issued to b, not b's audience
    assert revoke(user_api, b, tok).status_code == 200                         # silently ignored
    assert intro(user_api, a, tok).json()["active"] is True


def test_default_clients_still_get_jwts(super_admin, user_api):
    c = mk_service(super_admin)
    assert c["access_token_format"] == "jwt" and cc(user_api, c).json()["access_token"].count(".") == 2


def test_user_opaque_token_userinfo_introspection_and_revocation(db, super_admin, user_api, anon):
    c, body = start(super_admin, user_api, client_type="confidential", access_token_format="opaque")
    at = body["access_token"]
    assert at.startswith("idf_at_")
    r = anon.c.get("/oauth/userinfo", headers=bearer(at))
    assert r.status_code == 200 and r.json()["sub"]
    assert intro(user_api, c, at).json()["active"] is True
    assert revoke(user_api, c, at).status_code == 200
    assert anon.c.get("/oauth/userinfo", headers=bearer(at)).status_code == 401
    assert intro(user_api, c, at).json() == {"active": False}


def test_deactivating_the_user_kills_opaque_tokens_at_once(db, super_admin, user_api, anon):
    c, body = start(super_admin, user_api, client_type="confidential", access_token_format="opaque")
    at = body["access_token"]
    assert anon.c.get("/oauth/userinfo", headers=bearer(at)).status_code == 200
    assert super_admin.patch(f"/admin/users/{user_api.user.id}", {"status": "suspended"}).status_code == 200
    assert anon.c.get("/oauth/userinfo", headers=bearer(at)).status_code == 401
    assert intro(user_api, c, at).json() == {"active": False}


def test_switching_format_applies_to_new_tokens(super_admin, user_api):
    c = mk_service(super_admin)
    assert super_admin.patch(f"/admin/oidc/clients/{c['id']}", {"access_token_format": "opaque"}).json()["access_token_format"] == "opaque"
    assert cc(user_api, c).json()["access_token"].startswith("idf_at_")
    assert super_admin.patch(f"/admin/oidc/clients/{c['id']}", {"access_token_format": "bogus"}).status_code == 422


def test_revoke_cors_only_for_public_clients_from_their_origin(super_admin, user_api):
    c, body = start(super_admin, user_api)                       # public client, redirect URI on CB's origin
    origin = "http://localhost:5555"
    from urllib.parse import urlsplit
    origin = f"{urlsplit(CB).scheme}://{urlsplit(CB).netloc}"
    pre = user_api.c.options("/oauth/revoke", headers={"Origin": origin, "Access-Control-Request-Method": "POST"})
    assert pre.status_code == 204 and pre.headers["access-control-allow-origin"] == origin
    ok = user_api.c.post("/oauth/revoke", data={"token": body["refresh_token"], "client_id": c["client_id"]}, headers={"Origin": origin})
    assert ok.status_code == 200 and ok.headers["access-control-allow-origin"] == origin
    bad = user_api.c.post("/oauth/revoke", data={"token": "x", "client_id": c["client_id"]}, headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in bad.headers
    assert "access-control-allow-credentials" not in ok.headers


# ---- IFORA-47 / SEC-B-1: entitlement is rechecked after the token was issued ----------------

def _require_assignment(super_admin, required=True):
    app_id = super_admin.get("/admin/applications").json()["items"][0]["id"]
    cur = super_admin.get(f"/admin/applications/{app_id}").json()
    r = super_admin.put(f"/admin/applications/{app_id}", {"name": cur["name"], "sign_on_mode": "oidc", "require_assignment": required})
    assert r.status_code == 200, r.text
    return app_id


def test_unassigned_user_cannot_refresh_and_family_is_revoked(db, super_admin, user_api):
    from tests.test_oidc_refresh import refresh
    c, body = start(super_admin, user_api, client_type="confidential")
    _require_assignment(super_admin)                                    # the user was never assigned
    r = refresh(user_api, c, body["refresh_token"])
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"
    assert refresh(user_api, c, body["refresh_token"]).status_code == 400


def test_assigned_user_can_still_refresh(db, super_admin, user_api):
    from tests.test_oidc_refresh import refresh
    c, body = start(super_admin, user_api, client_type="confidential")
    app_id = _require_assignment(super_admin)
    assert super_admin.post(f"/admin/applications/{app_id}/assignments", {"user_id": user_api.user.id}).status_code == 201
    assert refresh(user_api, c, body["refresh_token"]).status_code == 200


def test_unassigned_user_opaque_token_and_refresh_token_are_inactive(db, super_admin, user_api, anon):
    c, body = start(super_admin, user_api, client_type="confidential", access_token_format="opaque")
    at, rt = body["access_token"], body["refresh_token"]
    assert intro(user_api, c, at).json()["active"] is True and intro(user_api, c, rt).json()["active"] is True
    _require_assignment(super_admin)
    assert intro(user_api, c, at).json() == {"active": False}
    assert intro(user_api, c, rt).json() == {"active": False}
    assert anon.c.get("/oauth/userinfo", headers=bearer(at)).status_code == 401
