"""Refresh tokens: issue, rotation, reuse detection, expiry, withdrawal of access, revocation endpoint."""

from datetime import timedelta

import pytest

from backend.app.audit.model import AuditEvent
from backend.app.config import settings
from backend.app.oidc import authorize as az, keys
from backend.app.oidc.models import OIDCClient, OIDCConsent, RefreshToken
from tests.conftest import Api, make_user
from tests.test_oidc_token import CB, VERIFIER, basic, exchange, get_code, post_token, user_api  # noqa: F401 (fixture)
from tests.test_oidc_token import mk as _mk

SCOPES = ["openid", "profile", "email", "offline_access"]
OFFLINE = "openid profile offline_access"


def mk(super_admin, **kw):
    return _mk(super_admin, allowed_scopes=SCOPES, **kw)


def start(super_admin, user_api, scope=OFFLINE, **kw):
    c = mk(super_admin, **kw)
    r = exchange(user_api, c, get_code(user_api, c, scope=scope))
    assert r.status_code == 200, r.text
    return c, r.json()


def refresh(api, client, token, **extra):
    data = {"grant_type": "refresh_token", "refresh_token": token, **extra}
    if client["client_type"] == "public":
        return post_token(api, {**data, "client_id": client["client_id"]})
    return post_token(api, data, basic(client))


def audit_count(db, action):
    return db.query(AuditEvent).filter(AuditEvent.action == action).count()


# ---- issuing ----------------------------------------------------------------------------------

def test_refresh_token_only_with_offline_access(db, super_admin, user_api):
    c, b = start(super_admin, user_api)
    assert b["refresh_token"].startswith("idf_rt_") and "offline_access" in b["scope"].split()
    row = db.query(RefreshToken).one()
    assert row.token_hash != b["refresh_token"] and len(row.token_hash) == 64        # hashed at rest
    assert row.absolute_expires_at - row.created_at <= timedelta(days=settings.OIDC_REFRESH_ABSOLUTE_DAYS, seconds=5)
    _, b2 = start(super_admin, user_api, scope="openid profile")
    assert "refresh_token" not in b2


def test_client_without_offline_access_scope_cannot_ask(super_admin, user_api):
    c = _mk(super_admin)  # default scopes: no offline_access
    r = user_api.c.get("/oauth/authorize", params={"client_id": c["client_id"], "redirect_uri": CB, "response_type": "code",
                                                   "scope": OFFLINE, "code_challenge": "a" * 43, "code_challenge_method": "S256"}, follow_redirects=False)
    assert "error=invalid_scope" in r.headers["location"]


# ---- rotation ---------------------------------------------------------------------------------

def test_refresh_rotates_and_returns_fresh_tokens(db, super_admin, user_api):
    c, first = start(super_admin, user_api)
    r = refresh(user_api, c, first["refresh_token"])
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["refresh_token"] != first["refresh_token"] and b["access_token"] != first["access_token"]
    assert b["scope"] == first["scope"] and r.headers["cache-control"] == "no-store"
    idt = keys.verify_jwt(db, b["id_token"], issuer=settings.OIDC_ISSUER, audience=c["client_id"])
    assert idt["sub"] == user_api.user.public_id and "nonce" not in idt and idt["amr"] == ["pwd"]
    assert keys.verify_jwt(db, b["access_token"], issuer=settings.OIDC_ISSUER, audience=settings.OIDC_ISSUER, typ="at+jwt")["client_id"] == c["client_id"]
    rows = db.query(RefreshToken).order_by(RefreshToken.id).all()
    assert len(rows) == 2 and rows[0].used_at is not None and rows[1].used_at is None and rows[0].family_id == rows[1].family_id
    assert rows[1].absolute_expires_at == rows[0].absolute_expires_at            # the hard cap never moves
    assert refresh(user_api, c, b["refresh_token"]).status_code == 200            # the chain continues


def test_reusing_a_rotated_token_revokes_the_whole_family(db, super_admin, user_api):
    c, first = start(super_admin, user_api)
    second = refresh(user_api, c, first["refresh_token"]).json()
    r = refresh(user_api, c, first["refresh_token"])                              # attacker replays the old one
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"
    assert audit_count(db, "OIDC_REFRESH_REUSE_DETECTED") == 1
    assert refresh(user_api, c, second["refresh_token"]).status_code == 400       # the legitimate holder is cut off too
    assert db.query(RefreshToken).filter(RefreshToken.revoked_at.is_(None)).count() == 0


def test_confidential_client_refresh(super_admin, user_api):
    c, first = start(super_admin, user_api, client_type="confidential")
    assert refresh(user_api, c, first["refresh_token"]).status_code == 200
    anon_try = post_token(user_api, {"grant_type": "refresh_token", "refresh_token": first["refresh_token"], "client_id": c["client_id"]})
    assert anon_try.status_code == 401                                            # a stolen token alone is not enough


def test_another_clients_refresh_token_is_refused_without_harm(super_admin, user_api):
    a, ta = start(super_admin, user_api)
    b = mk(super_admin, name="Other")
    r = refresh(user_api, b, ta["refresh_token"])
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"
    assert refresh(user_api, a, ta["refresh_token"]).status_code == 200


def test_unknown_or_missing_token(super_admin, user_api):
    c, _ = start(super_admin, user_api)
    assert refresh(user_api, c, "idf_rt_nope").json()["error"] == "invalid_grant"
    r = post_token(user_api, {"grant_type": "refresh_token", "client_id": c["client_id"]})
    assert r.status_code == 400 and r.json()["error"] == "invalid_request"


# ---- scope narrowing ----------------------------------------------------------------------------

def test_scope_can_be_narrowed_never_widened(super_admin, user_api):
    c, first = start(super_admin, user_api, scope="openid profile email offline_access")
    r = refresh(user_api, c, first["refresh_token"], scope="openid email")
    assert r.status_code == 200 and r.json()["scope"] == "openid email"
    wide = refresh(user_api, c, r.json()["refresh_token"], scope="openid email groups")
    assert wide.status_code == 400 and wide.json()["error"] == "invalid_scope"
    # the failed attempt spent its token (conservative) -- but a narrowed token never regains scopes
    c2, f2 = start(super_admin, user_api, scope="openid offline_access")
    assert refresh(user_api, c2, f2["refresh_token"], scope="openid profile").json()["error"] == "invalid_scope"


# ---- expiry -----------------------------------------------------------------------------------------

def test_idle_and_absolute_expiry(db, super_admin, user_api):
    c, first = start(super_admin, user_api)
    row = db.query(RefreshToken).one()
    row.expires_at = az.now() - timedelta(seconds=1)
    db.commit()
    assert refresh(user_api, c, first["refresh_token"]).json()["error"] == "invalid_grant"

    c, second = start(super_admin, user_api)
    row = db.query(RefreshToken).order_by(RefreshToken.id.desc()).first()
    row.absolute_expires_at = az.now() - timedelta(seconds=1)
    db.commit()
    assert refresh(user_api, c, second["refresh_token"]).json()["error"] == "invalid_grant"


def test_rotation_cannot_outlive_the_absolute_cap(db, super_admin, user_api):
    c, first = start(super_admin, user_api)
    row = db.query(RefreshToken).one()
    row.absolute_expires_at = az.now() + timedelta(hours=1)
    db.commit()
    assert refresh(user_api, c, first["refresh_token"]).status_code == 200
    newest = db.query(RefreshToken).order_by(RefreshToken.id.desc()).first()
    assert newest.expires_at <= newest.absolute_expires_at


# ---- access withdrawn --------------------------------------------------------------------------------

def test_deactivated_user_and_disabled_client_stop_refreshing(db, super_admin, user_api):
    c, first = start(super_admin, user_api)
    super_admin.patch(f"/admin/oidc/clients/{c['id']}", {"status": "disabled"})
    assert refresh(user_api, c, first["refresh_token"]).status_code == 401
    super_admin.patch(f"/admin/oidc/clients/{c['id']}", {"status": "active"})
    user_api.user.status = "inactive"
    db.commit()
    assert refresh(user_api, c, first["refresh_token"]).json()["error"] == "invalid_grant"


def third_party(db, super_admin, user_api):
    c = mk(super_admin, first_party=False)
    client = db.query(OIDCClient).filter(OIDCClient.client_id == c["client_id"]).one()
    az.record_consent(db, user_api.user.id, client, ["openid", "profile", "offline_access"], "user")
    db.commit()
    r = exchange(user_api, c, get_code(user_api, c, scope=OFFLINE))
    assert r.status_code == 200, r.text
    return c, client, r.json()


def test_withdrawing_consent_kills_refresh_tokens(db, super_admin, user_api):
    c, client, first = third_party(db, super_admin, user_api)
    listed = user_api.get("/me/consents").json()["items"]
    assert [i["name"] for i in listed] == ["Demo"] and "offline_access" in listed[0]["scopes"]
    assert user_api.delete(f"/me/consents/{client.id}").status_code == 200
    assert refresh(user_api, c, first["refresh_token"]).json()["error"] == "invalid_grant"
    assert user_api.get("/me/consents").json()["items"] == []
    assert audit_count(db, "OIDC_CONSENT_REVOKED") == 1
    assert user_api.delete(f"/me/consents/{client.id}").status_code == 404


def test_consent_withdrawal_is_per_user_and_not_for_first_party(db, super_admin, user_api):
    c, client, _ = third_party(db, super_admin, user_api)
    other = Api()
    make_user(db, "bob@example.com")
    assert other.login("bob@example.com").status_code == 200
    assert other.delete(f"/me/consents/{client.id}").status_code == 404
    fp, _ = start(super_admin, user_api, name="Portal")
    assert user_api.get("/me/consents").json()["items"][0]["client_pk"] == client.id   # first-party never listed
    assert user_api.delete(f"/me/consents/{fp['id']}").status_code == 404


def test_code_replay_revokes_refresh_tokens_issued_from_it(db, super_admin, user_api):
    c = mk(super_admin)
    code = get_code(user_api, c, scope=OFFLINE)
    first = exchange(user_api, c, code).json()
    assert exchange(user_api, c, code).status_code == 400                           # replay
    assert refresh(user_api, c, first["refresh_token"]).json()["error"] == "invalid_grant"


def test_missing_signing_config_does_not_spend_the_refresh_token(super_admin, user_api, monkeypatch):
    c, first = start(super_admin, user_api)
    monkeypatch.setattr(keys, "signing_key", lambda db: (_ for _ in ()).throw(keys.KeyConfigError("no key")))
    assert refresh(user_api, c, first["refresh_token"]).status_code == 503
    monkeypatch.undo()
    assert refresh(user_api, c, first["refresh_token"]).status_code == 200


# ---- /oauth/revoke --------------------------------------------------------------------------------------

def revoke(api, client, token, **extra):
    data = {"token": token, **extra}
    if client["client_type"] == "public":
        return post_token_to(api, "/oauth/revoke", {**data, "client_id": client["client_id"]})
    return post_token_to(api, "/oauth/revoke", data, basic(client))


def post_token_to(api, path, data, headers=None):
    return api.c.post(path, data=data, headers=headers or {})


def test_revoke_ends_the_family(db, super_admin, user_api):
    c, first = start(super_admin, user_api)
    second = refresh(user_api, c, first["refresh_token"]).json()
    assert revoke(user_api, c, second["refresh_token"]).status_code == 200
    assert refresh(user_api, c, second["refresh_token"]).json()["error"] == "invalid_grant"
    assert audit_count(db, "OIDC_TOKEN_REVOKED") == 1
    assert revoke(user_api, c, second["refresh_token"]).status_code == 200          # idempotent
    assert audit_count(db, "OIDC_TOKEN_REVOKED") == 1


def test_revoke_with_confidential_client_requires_auth(super_admin, user_api):
    c, first = start(super_admin, user_api, client_type="confidential")
    assert post_token_to(user_api, "/oauth/revoke", {"token": first["refresh_token"], "client_id": c["client_id"]}).status_code == 401
    assert refresh(user_api, c, first["refresh_token"]).status_code == 200          # still alive
    assert revoke(user_api, c, "idf_rt_whatever").status_code == 200                 # unknown tokens do not reveal anything


def test_revoking_someone_elses_token_changes_nothing(super_admin, user_api):
    a, ta = start(super_admin, user_api)
    b = mk(super_admin, name="Other")
    assert revoke(user_api, b, ta["refresh_token"]).status_code == 200
    assert refresh(user_api, a, ta["refresh_token"]).status_code == 200


def test_access_tokens_cannot_be_revoked_and_say_so(super_admin, user_api):
    c, first = start(super_admin, user_api)
    r = revoke(user_api, c, first["access_token"])
    assert r.status_code == 400 and r.json()["error"] == "unsupported_token_type"
    assert revoke(user_api, c, first["refresh_token"], token_type_hint="access_token").json()["error"] == "unsupported_token_type"
    assert post_token_to(user_api, "/oauth/revoke", {"client_id": c["client_id"]}).status_code == 400
