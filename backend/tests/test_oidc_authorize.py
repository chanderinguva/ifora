"""/oauth/authorize + consent: validation order, PKCE, single-use requests, consent rules, first-party skip."""

import base64
import hashlib
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from backend.app.config import settings
from backend.app.oidc import authorize as az
from backend.app.oidc.models import AuthorizationCode, OIDCConsent, PendingAuthRequest
from tests.conftest import Api, make_user

CB = "https://demo.example.com/callback"
VERIFIER = "a" * 50
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()


def mk(super_admin, **kw):
    r = super_admin.post("/admin/oidc/clients", {"name": "Demo", "redirect_uris": [CB], **kw})
    assert r.status_code == 201, r.text
    return r.json()


def params(client, **kw):
    p = {"client_id": client["client_id"], "redirect_uri": CB, "response_type": "code", "scope": "openid profile",
         "state": "st123", "nonce": "n-1", "code_challenge": CHALLENGE, "code_challenge_method": "S256"}
    p.update(kw)
    return {k: v for k, v in p.items() if v is not None}


def authorize(api, p):
    return api.c.get("/oauth/authorize", params=p, follow_redirects=False)


def loc(r):
    u = urlsplit(r.headers["location"])
    return u, {k: v[0] for k, v in parse_qs(u.query).items()}


@pytest.fixture
def user_api(db):
    u = make_user(db, "alice@example.com")
    a = Api()
    assert a.login(u.email).status_code == 200
    a.user = u
    return a


# ---- errors that must NOT redirect (client / redirect URI untrusted) -----------------------------------

@pytest.mark.parametrize("override", [
    {"client_id": "nope"}, {"client_id": None}, {"redirect_uri": None},
    {"redirect_uri": CB + "/"}, {"redirect_uri": CB.upper()}, {"redirect_uri": "https://evil.example.com/callback"},
    {"redirect_uri": CB + "?x=1"}, {"redirect_uri": "https://demo.example.com"},
])
def test_untrusted_client_or_redirect_is_shown_never_redirected(super_admin, anon, override):
    c = mk(super_admin)
    r = authorize(anon, params(c, **override))
    assert r.status_code == 400 and "location" not in r.headers
    assert r.json()["error"] == "invalid_request"


def test_disabled_client_is_not_redirected(super_admin, anon):
    c = mk(super_admin)
    super_admin.patch(f"/admin/oidc/clients/{c['id']}", {"status": "disabled"})
    assert authorize(anon, params(c)).status_code == 400


def test_repeated_parameters_are_rejected(super_admin, anon):
    c = mk(super_admin)
    r = anon.c.get(f"/oauth/authorize?client_id={c['client_id']}&client_id=x&redirect_uri={CB}", follow_redirects=False)
    assert r.status_code == 400


# ---- errors returned to the (now trusted) redirect URI -------------------------------------------------

@pytest.mark.parametrize("override,error", [
    ({"response_type": "token"}, "unsupported_response_type"),
    ({"response_type": "id_token"}, "unsupported_response_type"),
    ({"code_challenge": None}, "invalid_request"),
    ({"code_challenge_method": "plain"}, "invalid_request"),
    ({"code_challenge_method": None}, "invalid_request"),
    ({"code_challenge": "short"}, "invalid_request"),
    ({"code_challenge": "a" * 43 + "!"}, "invalid_request"),
    ({"scope": "profile"}, "invalid_scope"),
    ({"scope": None}, "invalid_scope"),
    ({"scope": "openid groups"}, "invalid_scope"),          # not in the client's allow-list
    ({"scope": "openid made_up"}, "invalid_scope"),
    ({"request": "eyJ..."}, "request_not_supported"),
    ({"request_uri": "https://x/y"}, "request_not_supported"),
    ({"prompt": "bogus"}, "invalid_request"),
    ({"max_age": "abc"}, "invalid_request"),
    ({"max_age": "-1"}, "invalid_request"),
    ({"prompt": "none consent"}, "invalid_request"),
])
def test_validation_errors_redirect_with_state_and_iss(super_admin, anon, override, error):
    c = mk(super_admin)
    r = authorize(anon, params(c, **override))
    assert r.status_code == 303
    u, q = loc(r)
    assert f"{u.scheme}://{u.netloc}{u.path}" == CB
    assert q["error"] == error and q["state"] == "st123" and q["iss"] == settings.OIDC_ISSUER
    assert "code" not in q
    assert r.headers["cache-control"] == "no-store"


# ---- unauthenticated: pending request + UI hop ----------------------------------------------------------

def test_anonymous_parks_request_and_redirects_to_ui(db, super_admin, anon):
    c = mk(super_admin)
    r = authorize(anon, params(c))
    assert r.status_code == 303
    u, q = loc(r)
    assert r.headers["location"].startswith(settings.OIDC_LOGIN_UI_URL)
    raw = q["request_id"]
    row = db.query(PendingAuthRequest).one()
    assert row.request_hash != raw and len(raw) >= 40            # only the hash is stored
    assert row.code_challenge == CHALLENGE and row.scopes == ["openid", "profile"]


def test_prompt_none_without_session_is_login_required(super_admin, anon):
    c = mk(super_admin)
    r = authorize(anon, params(c, prompt="none"))
    _, q = loc(r)
    assert r.headers["location"].startswith(CB) and q["error"] == "login_required" and q["state"] == "st123"


# ---- consent flow (third party) --------------------------------------------------------------------------

def start(user_api, c, **kw):
    r = authorize(user_api, params(c, **kw))
    assert r.status_code == 303
    return loc(r)[1]["request_id"]


def test_third_party_needs_consent_then_code(db, super_admin, user_api):
    c = mk(super_admin)
    rid = start(user_api, c)
    v = user_api.get(f"/oidc/authorization-requests/{rid}").json()
    assert v["consent_required"] is True and v["client"]["first_party"] is False
    assert [s["name"] for s in v["scopes"]] == ["openid", "profile"] and v["user"]["email"] == "alice@example.com"

    r = user_api.post(f"/oidc/authorization-requests/{rid}/decision", {"approve": True})
    assert r.status_code == 200
    _, q = loc(type("R", (), {"headers": {"location": r.json()["redirect_to"]}}))
    assert q["state"] == "st123" and q["iss"] == settings.OIDC_ISSUER and len(q["code"]) >= 40

    code = db.query(AuthorizationCode).one()
    assert code.code_hash != q["code"]                           # hashed at rest
    assert code.code_challenge == CHALLENGE and code.redirect_uri == CB and code.nonce == "n-1"
    assert code.expires_at - code.created_at <= timedelta(seconds=settings.OIDC_CODE_TTL_SECONDS)
    assert code.amr == ["pwd"] and code.used_at is None
    assert db.query(OIDCConsent).one().granted_via == "user"

    # consent is remembered: next time straight to a code, no UI hop
    r2 = authorize(user_api, params(c))
    assert "code=" in r2.headers["location"] and r2.headers["location"].startswith(CB)


def test_request_is_single_use(db, super_admin, user_api):
    c = mk(super_admin)
    rid = start(user_api, c)
    assert user_api.post(f"/oidc/authorization-requests/{rid}/decision", {"approve": True}).status_code == 200
    assert user_api.post(f"/oidc/authorization-requests/{rid}/decision", {"approve": True}).status_code == 404
    assert user_api.get(f"/oidc/authorization-requests/{rid}").status_code == 404
    assert db.query(AuthorizationCode).count() == 1


def test_expired_request_is_refused(db, super_admin, user_api):
    c = mk(super_admin)
    rid = start(user_api, c)
    row = db.query(PendingAuthRequest).one()
    row.expires_at = az.now() - timedelta(seconds=1)
    db.commit()
    assert user_api.get(f"/oidc/authorization-requests/{rid}").status_code == 404
    assert user_api.post(f"/oidc/authorization-requests/{rid}/decision", {"approve": True}).status_code == 404
    assert db.query(AuthorizationCode).count() == 0


def test_unknown_request_id_and_auth_required(super_admin, user_api, anon):
    c = mk(super_admin)
    rid = start(user_api, c)
    assert user_api.get("/oidc/authorization-requests/nope").status_code == 404
    assert anon.get(f"/oidc/authorization-requests/{rid}").status_code == 401
    assert anon.post(f"/oidc/authorization-requests/{rid}/decision", {"approve": True}).status_code == 401


def test_decision_needs_csrf(super_admin, user_api):
    c = mk(super_admin)
    rid = start(user_api, c)
    assert user_api.post(f"/oidc/authorization-requests/{rid}/decision", {"approve": True}, csrf=False).status_code == 403
    # the failed attempt did not consume the request
    assert user_api.post(f"/oidc/authorization-requests/{rid}/decision", {"approve": True}).status_code == 200


def test_deny_returns_access_denied_and_no_code(db, super_admin, user_api):
    c = mk(super_admin)
    rid = start(user_api, c)
    r = user_api.post(f"/oidc/authorization-requests/{rid}/decision", {"approve": False})
    assert r.status_code == 200
    q = {k: v[0] for k, v in parse_qs(urlsplit(r.json()["redirect_to"]).query).items()}
    assert q["error"] == "access_denied" and q["state"] == "st123" and "code" not in q
    assert db.query(AuthorizationCode).count() == 0 and db.query(OIDCConsent).count() == 0


def test_wider_scopes_need_fresh_consent(db, super_admin, user_api):
    c = mk(super_admin, allowed_scopes=["openid", "profile", "email"])
    rid = start(user_api, c, scope="openid")
    user_api.post(f"/oidc/authorization-requests/{rid}/decision", {"approve": True})
    assert "code=" in authorize(user_api, params(c, scope="openid")).headers["location"]
    r = authorize(user_api, params(c, scope="openid email"))
    assert r.headers["location"].startswith(settings.OIDC_LOGIN_UI_URL)   # email was never granted


def test_prompt_consent_forces_screen_prompt_none_fails_when_consent_needed(super_admin, user_api):
    c = mk(super_admin)
    rid = start(user_api, c)
    user_api.post(f"/oidc/authorization-requests/{rid}/decision", {"approve": True})
    assert authorize(user_api, params(c, prompt="consent")).headers["location"].startswith(settings.OIDC_LOGIN_UI_URL)
    assert "code=" in authorize(user_api, params(c, prompt="none")).headers["location"]
    other = mk(super_admin, name="Other")
    _, q = loc(authorize(user_api, params(other, prompt="none")))
    assert q["error"] == "consent_required"


def test_revoked_consent_requires_consent_again(db, super_admin, user_api):
    c = mk(super_admin)
    rid = start(user_api, c)
    user_api.post(f"/oidc/authorization-requests/{rid}/decision", {"approve": True})
    row = db.query(OIDCConsent).one()
    row.revoked_at = az.now()
    db.commit()
    assert authorize(user_api, params(c)).headers["location"].startswith(settings.OIDC_LOGIN_UI_URL)


# ---- first-party ---------------------------------------------------------------------------------------

def test_first_party_skips_consent_screen_but_not_authentication(db, super_admin, user_api, anon):
    c = mk(super_admin, first_party=True)
    # signed in: straight to a code, with an implicit consent row for audit
    r = authorize(user_api, params(c))
    assert r.headers["location"].startswith(CB) and "code=" in r.headers["location"]
    assert db.query(OIDCConsent).one().granted_via == "first_party"
    # not signed in: still has to authenticate (goes to the UI)
    assert authorize(anon, params(c)).headers["location"].startswith(settings.OIDC_LOGIN_UI_URL)


def test_first_party_does_not_widen_scopes(super_admin, user_api):
    c = mk(super_admin, first_party=True)
    _, q = loc(authorize(user_api, params(c, scope="openid groups")))
    assert q["error"] == "invalid_scope"


def test_inactive_user_cannot_get_a_code(db, super_admin, user_api):
    c = mk(super_admin, first_party=True)
    user_api.user.status = "inactive"
    db.commit()
    r = authorize(user_api, params(c))
    assert r.headers["location"].startswith(settings.OIDC_LOGIN_UI_URL)  # session no longer valid: back to login
    assert db.query(AuthorizationCode).count() == 0


def test_code_records_actual_auth_facts(db, super_admin, user_api):
    c = mk(super_admin, first_party=True)
    authorize(user_api, params(c))
    code = db.query(AuthorizationCode).one()
    assert code.user_id == user_api.user.id and code.amr == ["pwd"] and code.auth_time is not None


def test_client_deleted_between_request_and_decision(db, super_admin, user_api):
    c = mk(super_admin)
    rid = start(user_api, c)
    super_admin.delete(f"/admin/oidc/clients/{c['id']}")
    assert user_api.post(f"/oidc/authorization-requests/{rid}/decision", {"approve": True}).status_code == 404
    assert db.query(AuthorizationCode).count() == 0
