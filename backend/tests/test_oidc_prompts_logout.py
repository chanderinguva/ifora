"""prompt=login / max_age / acr_values (forced re-authentication) and RP-initiated logout."""

import base64
import hashlib
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from backend.app.audit.model import AuditEvent
from backend.app.auth.session import Session as AuthSession
from backend.app.config import settings
from backend.app.oidc import authorize as az, keys
from backend.app.oidc.models import AuthorizationCode, PendingAuthRequest
from tests.conftest import Api, STRONG, make_user
from tests.test_oidc_authorize import CB, authorize, loc, params
from tests.test_oidc_refresh import SCOPES, refresh
from tests.test_oidc_token import CHALLENGE, exchange, get_code, user_api  # noqa: F401 (fixture)

BYE = "https://demo.example.com/signed-out"


def mk(super_admin, **kw):
    r = super_admin.post("/admin/oidc/clients", {"name": "Demo", "redirect_uris": [CB], "first_party": True,
                                                  "post_logout_redirect_uris": [BYE], "allowed_scopes": SCOPES, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def P(c, **kw):
    """authorize parameters whose PKCE challenge matches the verifier `exchange` sends"""
    return params(c, code_challenge=CHALLENGE, **kw)


def rid_of(r):
    return loc(r)[1]["request_id"]


def relogin(user_api):
    fresh = Api()
    assert fresh.login(user_api.user.email, STRONG).status_code == 200
    return fresh


# ---- prompt=login ---------------------------------------------------------------------------------------

def test_prompt_login_forces_a_fresh_sign_in_even_for_first_party(db, super_admin, user_api):
    c = mk(super_admin)
    r = authorize(user_api, params(c, prompt="login"))
    assert r.headers["location"].startswith(settings.OIDC_LOGIN_UI_URL)         # no SSO shortcut
    rid = rid_of(r)
    assert db.query(PendingAuthRequest).one().auth_after is not None
    assert user_api.get(f"/oidc/authorization-requests/{rid}").json()["reauth_required"] is True
    d = user_api.post(f"/oidc/authorization-requests/{rid}/decision", {"approve": True})
    assert d.status_code == 403 and d.json()["detail"] == "reauthentication_required"
    assert db.query(AuthorizationCode).count() == 0

    fresh = relogin(user_api)                                                   # the user signs in again
    assert fresh.get(f"/oidc/authorization-requests/{rid}").json()["reauth_required"] is False
    ok = fresh.post(f"/oidc/authorization-requests/{rid}/decision", {"approve": True})
    assert ok.status_code == 200, ok.text
    code = db.query(AuthorizationCode).one()
    assert code.auth_time >= db.query(PendingAuthRequest).one().auth_after       # the code records the NEW authentication


def test_the_refused_decision_does_not_consume_the_request(db, super_admin, user_api):
    c = mk(super_admin)
    rid = rid_of(authorize(user_api, params(c, prompt="login")))
    for _ in range(2):
        assert user_api.post(f"/oidc/authorization-requests/{rid}/decision", {"approve": True}).status_code == 403
    assert db.query(PendingAuthRequest).one().decided_at is None


def test_prompt_login_without_a_session_still_marks_the_request(db, super_admin, anon):
    c = mk(super_admin)
    rid_of(authorize(anon, params(c, prompt="login")))
    assert db.query(PendingAuthRequest).one().auth_after is not None


def test_prompt_none_cannot_force_login(super_admin, user_api):
    c = mk(super_admin)
    assert "error" not in authorize(user_api, params(c, prompt="none")).headers["location"]   # plain SSO still fine
    _, q = loc(authorize(user_api, params(c, prompt="none", max_age="0")))
    assert q["error"] == "login_required"


def test_select_account_is_accepted_and_changes_nothing(super_admin, user_api):
    c = mk(super_admin)
    assert "code=" in authorize(user_api, params(c, prompt="select_account")).headers["location"]


# ---- max_age ----------------------------------------------------------------------------------------------

def test_max_age_within_limit_is_sso_and_beyond_it_reauthenticates(db, super_admin, user_api):
    c = mk(super_admin)
    assert "code=" in authorize(user_api, params(c, max_age="3600")).headers["location"]
    s = db.query(AuthSession).filter(AuthSession.user_id == user_api.user.id).one()
    s.auth_time = az.now() - timedelta(hours=2)
    db.commit()
    assert "code=" in authorize(user_api, params(c, max_age="86400")).headers["location"]
    r = authorize(user_api, params(c, max_age="60"))
    assert r.headers["location"].startswith(settings.OIDC_LOGIN_UI_URL)


def test_max_age_zero_always_reauthenticates(super_admin, user_api):
    c = mk(super_admin)
    assert authorize(user_api, params(c, max_age="0")).headers["location"].startswith(settings.OIDC_LOGIN_UI_URL)


def test_id_token_carries_auth_time_of_the_fresh_login(db, super_admin, user_api):
    c = mk(super_admin)
    rid = rid_of(authorize(user_api, P(c, prompt="login")))
    fresh = relogin(user_api)
    r = fresh.post(f"/oidc/authorization-requests/{rid}/decision", {"approve": True})
    code = parse_qs(urlsplit(r.json()["redirect_to"]).query)["code"][0]
    t = exchange(user_api, c, code).json()
    idt = keys.verify_jwt(db, t["id_token"], issuer=settings.OIDC_ISSUER, audience=c["client_id"])
    assert idt["auth_time"] >= int(db.query(PendingAuthRequest).one().auth_after.timestamp()) - 1


# ---- acr_values ---------------------------------------------------------------------------------------------

def test_acr_values_met_by_session_is_sso_otherwise_one_sign_in(db, super_admin, user_api):
    c = mk(super_admin)
    assert "code=" in authorize(user_api, P(c, acr_values="urn:identityforge:acr:1")).headers["location"]
    rid = rid_of(authorize(user_api, P(c, acr_values="urn:identityforge:acr:2")))   # password-only session is below acr:2
    fresh = relogin(user_api)
    # voluntary request: after one sign-in the flow proceeds and reports the level actually reached
    r = fresh.post(f"/oidc/authorization-requests/{rid}/decision", {"approve": True})
    assert r.status_code == 200
    code = parse_qs(urlsplit(r.json()["redirect_to"]).query)["code"][0]
    idt = keys.verify_jwt(db, exchange(user_api, c, code).json()["id_token"], issuer=settings.OIDC_ISSUER, audience=c["client_id"])
    assert idt["acr"] == "urn:identityforge:acr:1"


# ---- RP-initiated logout --------------------------------------------------------------------------------------

def id_token_for(db, super_admin, user_api, **kw):
    c = mk(super_admin, **kw)
    t = exchange(user_api, c, get_code(user_api, c)).json()
    return c, t["id_token"]


def body(**kw):
    return {k: v for k, v in kw.items() if v is not None}


def test_entry_point_forwards_only_known_parameters_to_the_ui(anon):
    r = anon.c.get("/oauth/logout", params={"id_token_hint": "abc", "state": "s", "evil": "x", "post_logout_redirect_uri": BYE},
                   follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith(settings.OIDC_LOGOUT_UI_URL)
    q = parse_qs(urlsplit(r.headers["location"]).query)
    assert set(q) == {"id_token_hint", "state", "post_logout_redirect_uri"}


def test_logout_ends_session_and_redirects_to_registered_uri_with_state(db, super_admin, user_api):
    c, hint = id_token_for(db, super_admin, user_api)
    info = user_api.get("/oidc/logout-request", params={"id_token_hint": hint, "post_logout_redirect_uri": BYE}).json()
    assert info == {"client_name": "Demo", "will_redirect": True, "signed_in_as": "alice@example.com"}
    r = user_api.post("/oidc/logout", body(id_token_hint=hint, post_logout_redirect_uri=BYE, state="xyz"))
    assert r.status_code == 200 and r.json()["redirect_to"] == BYE + "?state=xyz"
    assert user_api.get("/me").status_code == 401                                   # session is gone
    assert db.query(AuditEvent).filter(AuditEvent.action == "OIDC_LOGOUT").count() == 1


def test_expired_id_token_hint_is_accepted(db, super_admin, user_api):
    c = mk(super_admin)
    old = keys.sign_jwt(db, {"iss": settings.OIDC_ISSUER, "sub": user_api.user.public_id, "aud": c["client_id"], "iat": 1, "exp": 2})
    r = user_api.post("/oidc/logout", body(id_token_hint=old, post_logout_redirect_uri=BYE))
    assert r.json()["redirect_to"] == BYE


@pytest.mark.parametrize("uri", [BYE + "/", BYE + "?x=1", "https://demo.example.com/signed-out2", "https://evil.example.com/signed-out",
                                 "https://DEMO.example.com/signed-out", "javascript:alert(1)"])
def test_unregistered_post_logout_uris_are_never_used(db, super_admin, user_api, uri):
    c, hint = id_token_for(db, super_admin, user_api)
    r = user_api.post("/oidc/logout", body(id_token_hint=hint, post_logout_redirect_uri=uri))
    assert r.status_code == 200 and r.json()["redirect_to"] is None
    assert user_api.get("/me").status_code == 401                                   # the user is still signed out


def test_bad_hints_never_redirect(db, super_admin, user_api):
    c, hint = id_token_for(db, super_admin, user_api)
    tampered = hint[:-4] + ("AAAA" if not hint.endswith("AAAA") else "BBBB")
    for h in (tampered, "garbage", hint.split(".")[0] + "." + hint.split(".")[1]):
        fresh = relogin(user_api)
        assert fresh.post("/oidc/logout", body(id_token_hint=h, post_logout_redirect_uri=BYE)).json()["redirect_to"] is None


def test_redirect_needs_a_hint_or_client_id(db, super_admin, user_api):
    c, hint = id_token_for(db, super_admin, user_api)
    assert user_api.post("/oidc/logout", body(post_logout_redirect_uri=BYE)).json()["redirect_to"] is None
    fresh = relogin(user_api)
    assert fresh.post("/oidc/logout", body(client_id=c["client_id"], post_logout_redirect_uri=BYE)).json()["redirect_to"] == BYE


def test_client_id_must_agree_with_the_hint_and_exist(db, super_admin, user_api):
    c, hint = id_token_for(db, super_admin, user_api)
    other = mk(super_admin, name="Other")
    assert user_api.post("/oidc/logout", body(id_token_hint=hint, client_id=other["client_id"], post_logout_redirect_uri=BYE)).json()["redirect_to"] is None
    fresh = relogin(user_api)
    assert fresh.post("/oidc/logout", body(client_id="idf_ghost", post_logout_redirect_uri=BYE)).json()["redirect_to"] is None


def test_hint_of_another_user_still_signs_out_but_does_not_redirect(db, super_admin, user_api):
    c, hint = id_token_for(db, super_admin, user_api)
    bob = Api()
    make_user(db, "bob@example.com")
    assert bob.login("bob@example.com").status_code == 200
    r = bob.post("/oidc/logout", body(id_token_hint=hint, post_logout_redirect_uri=BYE))
    assert r.json()["redirect_to"] is None and bob.get("/me").status_code == 401
    assert user_api.get("/me").status_code == 200                                   # alice's own session is untouched


def test_disabled_client_gets_no_redirect(db, super_admin, user_api):
    c, hint = id_token_for(db, super_admin, user_api)
    super_admin.patch(f"/admin/oidc/clients/{c['id']}", {"status": "disabled"})
    assert user_api.post("/oidc/logout", body(id_token_hint=hint, post_logout_redirect_uri=BYE)).json()["redirect_to"] is None


def test_logout_without_a_session_still_returns_the_redirect(db, super_admin, user_api, anon):
    c, hint = id_token_for(db, super_admin, user_api)
    r = anon.c.post("/api/v1/oidc/logout", json=body(id_token_hint=hint, post_logout_redirect_uri=BYE))
    assert r.status_code == 200 and r.json()["redirect_to"] == BYE
    assert anon.c.get("/api/v1/oidc/logout-request").json()["signed_in_as"] is None


def test_logout_requires_csrf_when_a_session_exists(db, super_admin, user_api):
    c, hint = id_token_for(db, super_admin, user_api)
    r = user_api.post("/oidc/logout", body(id_token_hint=hint), csrf=False)
    assert r.status_code == 403
    assert user_api.get("/me").status_code == 200                                   # a forged cross-site POST cannot sign anyone out


def test_refresh_tokens_survive_logout_by_design(db, super_admin, user_api):
    c = mk(super_admin)
    t = exchange(user_api, c, get_code(user_api, c, scope="openid offline_access")).json()
    user_api.post("/oidc/logout", body(id_token_hint=t["id_token"]))
    assert refresh(Api(), c, t["refresh_token"]).status_code == 200


def test_discovery_advertises_logout_and_prompts(anon):
    d = anon.c.get("/.well-known/openid-configuration").json()
    assert d["end_session_endpoint"].endswith("/oauth/logout") and "login" in d["prompt_values_supported"]
    assert "urn:identityforge:acr:2" in d["acr_values_supported"]
