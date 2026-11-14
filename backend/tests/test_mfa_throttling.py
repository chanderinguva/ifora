"""IFORA-23: throttling on account-security endpoints, enrolment-code lifecycle, session revocation on factor changes."""

from datetime import datetime, timedelta, timezone

import pyotp
import pytest

from backend.app import ratelimit
from backend.app.auth import mfa_service
from backend.app.auth.passkey_model import Passkey
from backend.app.config import settings
from backend.app.tenancy import Tenant, tenant_session, unscoped
from tests.conftest import STRONG, Api, make_user
from tests.test_mfa import enrol, totp_for
from tests.test_ratelimit_hardening import _DeadRedis

WRONG = "000000"


def _setup(db, email="thr@example.com"):
    """A signed-in user with an unconfirmed TOTP setup."""
    u = make_user(db, email)
    a = Api()
    a.login(u.email)
    a.user = u
    r = a.post("/me/mfa/setup", {"password": STRONG})
    assert r.status_code == 200
    a.secret = r.json()["secret"]
    return a


# --- 1. throttling --------------------------------------------------------------------------------------------------


def test_ten_wrong_codes_lock_enable_even_for_the_right_code(db):
    a = _setup(db)
    assert [a.post("/me/mfa/enable", {"code": WRONG}).status_code for _ in range(10)] == [400] * 10
    r = a.post("/me/mfa/enable", {"code": pyotp.TOTP(a.secret).now()})
    assert r.status_code == 429 and r.headers.get("retry-after")
    db.expire_all()
    assert a.user.mfa.enabled is False


def test_wrong_password_rechecks_are_throttled(db):
    u = make_user(db, "reauth@example.com")
    a = Api()
    a.login(u.email)
    assert [a.post("/me/mfa/setup", {"password": "Wrong-pass-1!"}).status_code for _ in range(10)] == [403] * 10
    assert a.post("/me/mfa/setup", {"password": STRONG}).status_code == 429


def test_disable_and_regenerate_count_wrong_codes(db):
    u = make_user(db, "both@example.com")
    a = Api()
    a.login(u.email)
    enrol(a, db, u.email)
    for _ in range(5):
        assert a.post("/me/mfa/disable", {"password": STRONG, "code": WRONG}).status_code == 400
    for _ in range(5):
        assert a.post("/me/mfa/recovery-codes", {"password": STRONG, "code": WRONG}).status_code == 400
    # one shared per-account budget: the next try, with everything correct, is refused
    assert a.post("/me/mfa/disable", {"password": STRONG, "code": totp_for(db, u.email)}).status_code == 429


def test_a_second_account_is_not_affected_by_anothers_failures(db):
    a = _setup(db, "one@example.com")
    for _ in range(10):
        a.post("/me/mfa/enable", {"code": WRONG})
    b = Api()
    other = make_user(db, "two@example.com")
    b.login(other.email)
    assert b.post("/me/mfa/setup", {"password": STRONG}).status_code == 200  # per-IP budget is twice the per-user one


def test_redis_down_refuses_security_endpoints(db, monkeypatch):
    a = _setup(db, "redisdown@example.com")
    monkeypatch.setattr(ratelimit, "_redis", lambda: _DeadRedis())
    r = a.post("/me/mfa/enable", {"code": pyotp.TOTP(a.secret).now()})
    assert r.status_code == 503
    assert a.post("/me/mfa/setup", {"password": STRONG}).status_code == 503


# --- 2. enrolment code lifecycle ------------------------------------------------------------------------------------


@pytest.fixture
def admin_needing_mfa(db, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_MFA_REQUIRED", True)
    u = make_user(db, "needs@example.com", admin=True)
    a = Api()
    assert a.login(u.email).status_code == 200
    a.user = u
    return a


def _issue(db, u):
    db.refresh(u)
    code = mfa_service.issue_enrollment_code(u)
    db.commit()
    return code


def test_enrolment_code_is_single_use(db, admin_needing_mfa):
    a, u = admin_needing_mfa, admin_needing_mfa.user
    code = _issue(db, u)
    assert a.post("/me/mfa/setup", {"password": STRONG, "enrollment_code": code}).status_code == 200
    assert a.post("/me/mfa/setup", {"password": STRONG, "enrollment_code": code}).status_code == 403
    db.refresh(u)
    assert u.enrollment_code_hash is None


def test_enrolment_code_expires(db, admin_needing_mfa):
    a, u = admin_needing_mfa, admin_needing_mfa.user
    code = _issue(db, u)
    u.enrollment_code_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    assert a.post("/me/mfa/setup", {"password": STRONG, "enrollment_code": code}).status_code == 403


def test_reissuing_invalidates_the_previous_code(db, admin_needing_mfa):
    a, u = admin_needing_mfa, admin_needing_mfa.user
    old = _issue(db, u)
    new = _issue(db, u)
    assert a.post("/me/mfa/setup", {"password": STRONG, "enrollment_code": old}).status_code == 403
    assert a.post("/me/mfa/setup", {"password": STRONG, "enrollment_code": new}).status_code == 200


def test_a_failed_setup_does_not_spend_the_code(db, admin_needing_mfa):
    a, u = admin_needing_mfa, admin_needing_mfa.user
    code = _issue(db, u)
    assert a.post("/me/mfa/setup", {"password": "Wrong-pass-1!", "enrollment_code": code}).status_code == 403
    assert a.post("/me/mfa/setup", {"password": STRONG, "enrollment_code": code}).status_code == 200


def test_guessing_enrolment_codes_is_throttled_per_account(db, admin_needing_mfa):
    a, u = admin_needing_mfa, admin_needing_mfa.user
    code = _issue(db, u)
    assert [a.post("/me/mfa/setup", {"password": STRONG, "enrollment_code": "AAAA-BBBB-CCCC"}).status_code
            for _ in range(10)] == [403] * 10
    assert a.post("/me/mfa/setup", {"password": STRONG, "enrollment_code": code}).status_code == 429


# --- 3. sessions end when a factor changes --------------------------------------------------------------------------


def _three_sessions(db, email):
    u = make_user(db, email)
    mine, o1, o2 = Api(), Api(), Api()
    for x in (mine, o1, o2):
        assert x.login(u.email).status_code == 200
    mine.user = u
    return mine, o1, o2


def _mfa_sessions(db, email):
    """The account has MFA on and three live sessions, each signed in with a code. Returns (mine, other1, other2)."""
    from tests.test_mfa import mfa_login, reset_replay

    u = make_user(db, email)
    mine = Api()
    mine.login(u.email)
    mine.user = u
    enrol(mine, db, email)  # enabling ends any other session; sign in twice more with both factors
    others = []
    for _ in range(2):
        reset_replay(db, email)
        api, _, r = mfa_login(db, email)
        assert r.status_code == 200
        others.append(api)
    reset_replay(db, email)
    return mine, others[0], others[1]


def test_disabling_mfa_ends_the_other_sessions(db):
    mine, o1, o2 = _mfa_sessions(db, "dis@example.com")
    assert o1.get("/me").status_code == o2.get("/me").status_code == 200
    r = mine.post("/me/mfa/disable", {"password": STRONG, "code": totp_for(db, mine.user.email)})
    assert r.status_code == 200
    assert mine.get("/me").status_code == 200
    assert o1.get("/me").status_code == 401 and o2.get("/me").status_code == 401


def test_regenerating_recovery_codes_ends_the_other_sessions(db):
    mine, o1, o2 = _mfa_sessions(db, "regen@example.com")
    r = mine.post("/me/mfa/recovery-codes", {"password": STRONG, "code": totp_for(db, mine.user.email)})
    assert r.status_code == 200
    assert mine.get("/me").status_code == 200
    assert o1.get("/me").status_code == 401 and o2.get("/me").status_code == 401


def test_removing_a_passkey_ends_the_other_sessions(db):
    mine, o1, o2 = _three_sessions(db, "pk@example.com")
    pk = Passkey(user_id=mine.user.id, credential_id="cred-1", public_key=b"k", name="Key")
    db.add(pk)
    db.commit()
    r = mine.post(f"/me/passkeys/{pk.id}/remove", {"password": STRONG})
    assert r.status_code == 200
    assert mine.get("/me").status_code == 200
    assert o1.get("/me").status_code == 401 and o2.get("/me").status_code == 401


def test_admin_reset_ends_every_session(db, admin):
    mine, o1, o2 = _mfa_sessions(db, "adminreset@example.com")
    assert admin.post(f"/admin/users/{mine.user.id}/mfa/reset").status_code == 200
    assert all(x.get("/me").status_code == 401 for x in (mine, o1, o2))


# --- 5. tenant boundary ---------------------------------------------------------------------------------------------


def test_admin_cannot_reset_another_tenants_user(db, admin):
    with unscoped(db):
        t2 = Tenant(slug="other", name="Other")
        db.add(t2)
        db.commit()
        tid2 = t2.id
    other = tenant_session(tid2)
    try:
        victim = make_user(other, "victim@other.example")
        assert admin.post(f"/admin/users/{victim.id}/mfa/reset").status_code == 404
        assert admin.post(f"/admin/users/{victim.id}/enrollment-code").status_code in (403, 404)
    finally:
        other.close()
