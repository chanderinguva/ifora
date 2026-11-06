"""Sessions record when and how the user authenticated (feeds OIDC auth_time / amr / acr, ADR 005)."""

from datetime import datetime, timedelta, timezone

from backend.app.auth.authn import ACR_MULTI_FACTOR, ACR_SINGLE_FACTOR, acr_for, amr_for
from backend.app.auth.session import Session as AuthSession
from tests.conftest import Api, make_user
from tests.test_mfa import enrol, mfa_login
from tests.test_passkeys import passkey_login, register


def _facts(api):
    return api.get("/me").json()["session"]


def _recent(ts):
    return abs(datetime.now(timezone.utc) - datetime.fromisoformat(ts)) < timedelta(seconds=30)


def test_password_login_records_pwd_single_factor(member):
    s = _facts(member)
    assert s["amr"] == ["pwd"] and s["acr"] == ACR_SINGLE_FACTOR and _recent(s["auth_time"])


def test_login_response_carries_the_same_facts(db):
    make_user(db, "a@example.com")
    r = Api().login("a@example.com")
    assert r.json()["session"]["amr"] == ["pwd"] and r.json()["session"]["acr"] == ACR_SINGLE_FACTOR


def test_totp_login_is_multi_factor(db):
    u = make_user(db, "m@example.com")
    a = Api()
    a.login(u.email)
    enrol(a, db, u.email)
    api, _, r2 = mfa_login(db, u.email)
    assert r2.status_code == 200
    s = _facts(api)
    assert s["amr"] == ["pwd", "otp", "mfa"] and s["acr"] == ACR_MULTI_FACTOR


def test_recovery_code_login_is_multi_factor(db):
    u = make_user(db, "m@example.com")
    a = Api()
    a.login(u.email)
    codes = enrol(a, db, u.email)
    api, _, r2 = mfa_login(db, u.email, code=codes[0])
    assert r2.status_code == 200 and _facts(api)["acr"] == ACR_MULTI_FACTOR


def test_passkey_login_is_multi_factor(member):
    auth, r = register(member)
    assert r.status_code == 201
    api, _ = passkey_login(auth)
    s = _facts(api)
    assert s["amr"] == ["hwk", "user", "mfa"] and s["acr"] == ACR_MULTI_FACTOR


def test_auth_time_does_not_move_with_activity(db, member):
    row = db.query(AuthSession).one()
    old = row.auth_time - timedelta(hours=2)
    row.auth_time = old
    db.commit()
    member.get("/me")  # activity touches last_activity_at only
    db.expire_all()
    assert db.query(AuthSession).one().auth_time == old


def test_unknown_method_never_claims_mfa():
    assert amr_for("something-new") == ["pwd"]
    assert acr_for(["pwd"]) == ACR_SINGLE_FACTOR and acr_for(None) == ACR_SINGLE_FACTOR


def test_amr_is_server_side_only(member):
    # a client cannot influence it through any request field
    r = member.post("/me/role/user", {"amr": ["mfa"]})
    assert r.status_code in (200, 400)
    assert _facts(member)["amr"] == ["pwd"]
