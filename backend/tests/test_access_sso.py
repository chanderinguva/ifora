"""Sign in with a Cloudflare Access identity token (demo environments)."""

import time

import pytest
from joserfc import jwt
from joserfc.jwk import RSAKey

from backend.app import config_guards
from backend.app.auth import access_sso
from backend.app.auth.access_sso import HEADER
from backend.app.auth.mfa_model import UserMFA
from backend.app.auth.session import Session as AuthSession
from backend.app.config import settings
from backend.app.users.model import User
from tests.conftest import ORIGIN, STRONG, Api, make_user
from tests.test_config_guards import make_production_valid

TEAM = "demo-team.cloudflareaccess.com"
AUD = "a" * 64
KEY = RSAKey.generate_key(2048, parameters={"kid": "k1"})
OTHER_KEY = RSAKey.generate_key(2048, parameters={"kid": "k1"})  # same kid, different material


def token(email="friend@example.com", key=KEY, iss=f"https://{TEAM}", aud=None, exp=None, alg="RS256", **extra):
    claims = {"email": email, "iss": iss, "aud": [AUD] if aud is None else aud,
              "exp": int(time.time()) + 300 if exp is None else exp, "iat": int(time.time()), **extra}
    return jwt.encode({"alg": alg, "kid": "k1"}, claims, key)


@pytest.fixture(autouse=True)
def sso(monkeypatch):
    monkeypatch.setattr(settings, "ACCESS_SSO_ENABLED", True)
    monkeypatch.setattr(settings, "ACCESS_TEAM_DOMAIN", TEAM)
    monkeypatch.setattr(settings, "ACCESS_AUD", AUD)
    monkeypatch.setattr(settings, "ACCESS_SSO_AUTO_CREATE", True)
    monkeypatch.setattr(access_sso, "_fetch_jwks", lambda: {"keys": [KEY.as_dict(private=False)]})
    access_sso.reset_cache()
    yield
    access_sso.reset_cache()


def go(api, tok=None, origin=ORIGIN):
    headers = {"Origin": origin}
    if tok is not None:
        headers[HEADER] = tok
    r = api.c.post("/api/v1/login/access", headers=headers)
    if r.status_code == 200:
        api.csrf = r.json()["csrf_token"]
    return r


def test_disabled_by_default_is_not_found(monkeypatch):
    monkeypatch.setattr(settings, "ACCESS_SSO_ENABLED", False)
    api = Api()
    assert go(api, token()).status_code == 404
    assert api.get("/login/access/enabled").json() == {"enabled": False}


def test_enabled_flag_is_public(anon):
    assert anon.get("/login/access/enabled").json() == {"enabled": True}


def test_no_header_is_unauthorised_and_creates_nothing(db, anon):
    assert go(anon).status_code == 401
    assert db.query(User).count() == 0
    assert db.query(AuthSession).count() == 0


def test_valid_token_creates_a_non_admin_guest_and_a_session(db, anon):
    r = go(anon, token("New.Friend@Example.com"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["first_visit"] is True and body["user"]["email"] == "new.friend@example.com"
    u = db.query(User).one()
    assert (u.is_admin, u.is_super_admin, u.status) == (False, False, "active")
    assert u.password_changed_at is None and u.username == "new.friend"
    assert anon.get("/me").json()["user"]["email"] == "new.friend@example.com"
    assert db.query(AuthSession).one().amr == ["otp"]


def test_existing_user_is_matched_case_insensitively_and_not_duplicated(db, anon):
    make_user(db, "friend@example.com")
    r = go(anon, token("FRIEND@example.com"))
    assert r.status_code == 200 and r.json()["first_visit"] is False
    assert db.query(User).count() == 1


def test_username_clash_gets_a_suffix(db):
    make_user(db, "other@example.org", username="friend")
    assert go(Api(), token("friend@example.com")).status_code == 200
    assert sorted(u.username for u in db.query(User)) == ["friend", "friend2"]


def test_auto_create_off_refuses_unknown_email(db, monkeypatch, anon):
    monkeypatch.setattr(settings, "ACCESS_SSO_AUTO_CREATE", False)
    assert go(anon, token()).status_code == 401
    assert db.query(User).count() == 0


@pytest.mark.parametrize("label,kwargs", [
    ("wrong audience", {"aud": ["b" * 64]}),
    ("no audience", {"aud": []}),
    ("wrong issuer", {"iss": "https://evil.cloudflareaccess.com"}),
    ("expired", {"exp": int(time.time()) - 3600}),
    ("signed by another key", {"key": OTHER_KEY}),
])
def test_bad_tokens_are_refused_without_side_effects(db, anon, label, kwargs):
    assert go(anon, token(**kwargs)).status_code == 401, label
    assert db.query(User).count() == 0 and db.query(AuthSession).count() == 0


def test_garbage_and_unsigned_tokens_are_refused(db, anon):
    assert go(anon, "not-a-jwt").status_code == 401
    import base64, json

    def b64(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()

    unsigned = f"{b64({'alg': 'none', 'kid': 'k1'})}.{b64({'email': 'x@example.com', 'iss': f'https://{TEAM}', 'aud': [AUD], 'exp': int(time.time()) + 99})}."
    assert go(anon, unsigned).status_code == 401
    hs = jwt.encode({"alg": "HS256", "kid": "k1"}, {"email": "x@example.com", "iss": f"https://{TEAM}", "aud": [AUD], "exp": int(time.time()) + 99},
                    __import__("joserfc.jwk", fromlist=["OctKey"]).OctKey.import_key("k" * 40))
    assert go(anon, hs).status_code == 401  # algorithm confusion
    assert db.query(User).count() == 0


def test_token_without_email_is_refused(anon):
    claims = {"iss": f"https://{TEAM}", "aud": [AUD], "exp": int(time.time()) + 99}
    assert go(anon, jwt.encode({"alg": "RS256", "kid": "k1"}, claims, KEY)).status_code == 401


def test_foreign_origin_is_refused(anon):
    assert go(anon, token(), origin="https://evil.example").status_code == 403


def test_repeated_bad_tokens_hit_the_login_limiter(anon):
    codes = [go(anon, token(aud=["b" * 64])).status_code for _ in range(settings.RATE_LIMIT_LOGIN_FAILURES + 2)]
    assert codes[0] == 401 and codes[-1] == 429


def test_unknown_key_id_refetches_once_then_gives_up(monkeypatch, anon):
    calls = []
    monkeypatch.setattr(access_sso, "_fetch_jwks", lambda: calls.append(1) or {"keys": [OTHER_KEY.as_dict(private=False)]})
    access_sso.reset_cache()
    for _ in range(3):
        assert go(anon, token()).status_code == 401
    assert len(calls) <= 2  # initial fetch plus at most one forced refresh within the throttle window


def test_jwks_outage_fails_closed(monkeypatch, anon):
    def boom():
        raise RuntimeError("down")

    monkeypatch.setattr(access_sso, "_fetch_jwks", boom)
    access_sso.reset_cache()
    assert go(anon, token()).status_code == 401


# --- accounts that must keep the stronger path ---------------------------------------------------------------

def test_administrators_are_never_signed_in_this_way(db, anon):
    make_user(db, "root@example.com", super_admin=True)
    make_user(db, "adm@example.com", admin=True)
    for email in ("root@example.com", "adm@example.com"):
        assert go(anon, token(email)).status_code == 403
    assert db.query(AuthSession).count() == 0


def test_accounts_with_totp_or_required_passkey_are_refused(db, anon):
    a = make_user(db, "totp@example.com")
    db.add(UserMFA(user_id=a.id, secret_encrypted="x", enabled=True))
    b = make_user(db, "pk@example.com")
    b.passkey_required = True
    db.commit()
    for email in ("totp@example.com", "pk@example.com"):
        assert go(anon, token(email)).status_code == 403
    assert db.query(AuthSession).count() == 0


@pytest.mark.parametrize("status", ["suspended", "deprovisioned", "password_expired", "provisioned"])
def test_inactive_accounts_are_refused(db, anon, status):
    u = make_user(db, "friend@example.com")
    u.status = status
    db.commit()
    assert go(anon, token()).status_code == 403
    assert db.query(AuthSession).count() == 0


# --- first visit: choose a password -------------------------------------------------------------------------

def test_first_visit_password_then_password_login_works(db, anon):
    assert go(anon, token()).json()["first_visit"] is True
    assert anon.post("/me/password/initial", {"new_password": STRONG}).status_code == 200
    u = db.query(User).one()
    assert u.password_changed_at is not None and u.verify_password(STRONG)
    # no longer a first visit, and the new password signs in without Access
    assert go(Api(), token()).json()["first_visit"] is False
    assert Api().login("friend@example.com", STRONG).status_code == 200
    # one-shot: the account now has a password of its own
    assert anon.post("/me/password/initial", {"new_password": STRONG + "z"}).status_code == 403


def test_first_visit_password_must_meet_policy(db, anon):
    go(anon, token())
    r = anon.post("/me/password/initial", {"new_password": "short"})
    assert r.status_code in (400, 422)
    assert db.query(User).one().password_changed_at is None


def test_first_visit_password_other_sessions_are_revoked(db, anon):
    go(anon, token())
    other = Api()
    go(other, token())
    assert anon.post("/me/password/initial", {"new_password": STRONG}).status_code == 200
    assert other.get("/me").status_code == 401 and anon.get("/me").status_code == 200


def test_initial_password_is_refused_for_password_sessions(member):
    assert member.post("/me/password/initial", {"new_password": STRONG + "q"}).status_code == 403


def test_initial_password_is_refused_for_a_totp_session_even_without_a_password_date(db, member):
    # a session that lists "otp" because of TOTP (not Access), on an account with no recorded password date
    u = db.query(User).one()
    u.password_changed_at = None
    s = db.query(AuthSession).one()
    s.amr = ["pwd", "otp", "mfa"]
    db.commit()
    assert member.post("/me/password/initial", {"new_password": STRONG + "q"}).status_code == 403
    assert db.query(User).one().verify_password(STRONG)


def test_initial_password_requires_a_session(anon):
    assert anon.post("/me/password/initial", {"new_password": STRONG}, csrf=False).status_code == 401


# --- configuration -------------------------------------------------------------------------------------------

def test_production_requires_team_and_audience_when_enabled(monkeypatch):
    make_production_valid(monkeypatch)
    assert config_guards.validate_settings(settings) == []
    monkeypatch.setattr(settings, "ACCESS_AUD", "")
    assert any("ACCESS_SSO_ENABLED" in p for p in config_guards.validate_settings(settings))
    monkeypatch.setattr(settings, "ACCESS_AUD", AUD)
    monkeypatch.setattr(settings, "ACCESS_TEAM_DOMAIN", "https://x.cloudflareaccess.com/")
    assert any("ACCESS_SSO_ENABLED" in p for p in config_guards.validate_settings(settings))
