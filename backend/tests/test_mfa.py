"""TOTP multi-factor authentication."""

import time

import pyotp
import pytest

from backend.app.auth import mfa
from backend.app.auth.mfa_model import MFAChallenge, MFARecoveryCode, UserMFA
from backend.app.config import settings
from backend.app.users.model import User
from tests.conftest import ORIGIN, STRONG, Api, make_user


def totp_for(db, email, offset_steps=0):
    """A valid current code; clears replay state so tests can log in repeatedly within one step."""
    u = db.query(User).filter_by(email=email).one()
    db.expire_all()
    rec = db.query(UserMFA).filter_by(user_id=u.id).one()
    return pyotp.TOTP(mfa.decrypt_secret(rec.secret_encrypted)).at(int(time.time()) + 30 * offset_steps)


def reset_replay(db, email):
    u = db.query(User).filter_by(email=email).one()
    db.query(UserMFA).filter_by(user_id=u.id).update({"last_used_step": None})
    db.commit()


def enrol(api, db, email, enrollment_code=None):
    """Run the full setup+enable flow; returns recovery codes."""
    r = api.post("/me/mfa/setup", {"password": STRONG, "enrollment_code": enrollment_code})
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]
    code = pyotp.TOTP(secret).now()
    r = api.post("/me/mfa/enable", {"code": code})
    assert r.status_code == 200, r.text
    reset_replay(db, email)
    return r.json()["recovery_codes"]


@pytest.fixture
def enrolled(db):
    u = make_user(db, "mfa@example.com")
    a = Api()
    a.login(u.email)
    a.user = u
    a.codes = enrol(a, db, u.email)
    return a


def mfa_login(db, email="mfa@example.com", code=None):
    """Password step then code step. Returns (api, step1_response, step2_response)."""
    api = Api()
    r1 = api.login(email)
    token = r1.json().get("mfa_token")
    r2 = api.c.post(
        "/api/v1/login/mfa",
        json={"mfa_token": token, "code": code if code is not None else totp_for(db, email)},
        headers={"Origin": ORIGIN},
    )
    if r2.status_code == 200:
        api.csrf = r2.json()["csrf_token"]
    return api, r1, r2


# ---- enrolment ----------------------------------------------------------------

def test_setup_requires_password(member):
    assert member.post("/me/mfa/setup", {"password": "WrongPassw0rd!!"}).status_code == 403


def test_enrolment_flow_and_secret_encrypted_at_rest(db, member):
    r = member.post("/me/mfa/setup", {"password": STRONG}).json()
    assert r["otpauth_uri"].startswith("otpauth://totp/") and "IdentityForge" in r["otpauth_uri"]
    stored = db.query(UserMFA).one().secret_encrypted
    assert r["secret"] not in stored and mfa.decrypt_secret(stored) == r["secret"]
    assert member.get("/me/mfa").json() == {"enabled": False, "pending": True, "recovery_codes_remaining": 0}
    assert member.post("/me/mfa/enable", {"code": "000000"}).status_code == 400
    out = member.post("/me/mfa/enable", {"code": pyotp.TOTP(r["secret"]).now()}).json()
    assert out["enabled"] and len(out["recovery_codes"]) == 10
    assert member.get("/me/mfa").json()["recovery_codes_remaining"] == 10
    assert member.get("/me").json()["user"]["mfa_enabled"] is True
    # recovery codes are stored hashed only
    plain = out["recovery_codes"][0]
    assert all(plain not in row.code_hash for row in db.query(MFARecoveryCode))


def test_cannot_setup_twice_when_enabled(db, enrolled):
    assert enrolled.post("/me/mfa/setup", {"password": STRONG}).status_code == 409


def test_enabling_revokes_other_sessions(db):
    u = make_user(db, "mfa@example.com")
    a, other = Api(), Api()
    a.login(u.email)
    other.login(u.email)
    enrol(a, db, u.email)
    assert a.get("/me").status_code == 200
    assert other.get("/me").status_code == 401


# ---- login ------------------------------------------------------------------

def test_password_alone_does_not_grant_a_session(db, enrolled):
    api = Api()
    r = api.login("mfa@example.com")
    assert r.status_code == 200 and r.json()["mfa_required"] is True and r.json()["success"] is False
    assert "set-cookie" not in r.headers and "user" not in r.json()
    assert api.get("/me").status_code == 401


def test_login_with_valid_totp(db, enrolled):
    api, r1, r2 = mfa_login(db)
    assert r2.status_code == 200 and "identityforge_session" in r2.headers["set-cookie"]
    assert api.get("/me").json()["user"]["email"] == "mfa@example.com"


def test_totp_code_cannot_be_replayed(db, enrolled):
    reset_replay(db, "mfa@example.com")
    code = totp_for(db, "mfa@example.com")
    _, _, r = mfa_login(db, code=code)
    assert r.status_code == 200
    _, _, again = mfa_login(db, code=code)  # same code, fresh challenge
    assert again.status_code == 401


def test_clock_drift_window(db, enrolled):
    _, _, ok = mfa_login(db, code=totp_for(db, "mfa@example.com", -1))
    assert ok.status_code == 200
    reset_replay(db, "mfa@example.com")
    _, _, too_old = mfa_login(db, code=totp_for(db, "mfa@example.com", -3))
    assert too_old.status_code == 401


def test_wrong_code_and_bad_token_are_rejected(db, enrolled):
    _, _, r = mfa_login(db, code="123456")
    assert r.status_code == 401 and r.json()["detail"] == "Invalid or expired code"
    api = Api()
    bad = api.c.post("/api/v1/login/mfa", json={"mfa_token": "nope", "code": totp_for(db, "mfa@example.com")}, headers={"Origin": ORIGIN})
    assert bad.status_code == 401


def test_challenge_dies_after_max_attempts_even_for_the_right_code(db, enrolled):
    api = Api()
    token = api.login("mfa@example.com").json()["mfa_token"]
    for _ in range(settings.MFA_CHALLENGE_MAX_ATTEMPTS - 1):
        r = api.c.post("/api/v1/login/mfa", json={"mfa_token": token, "code": "111111"}, headers={"Origin": ORIGIN})
        assert r.status_code == 401
    good = api.c.post("/api/v1/login/mfa", json={"mfa_token": token, "code": totp_for(db, "mfa@example.com")}, headers={"Origin": ORIGIN})
    assert good.status_code == 200  # still within the limit
    # new round: burn all attempts, then the right code is refused
    api2 = Api()
    t2 = api2.login("mfa@example.com").json()["mfa_token"]
    db.query(MFAChallenge).update({"attempts": settings.MFA_CHALLENGE_MAX_ATTEMPTS})
    db.commit()
    reset_replay(db, "mfa@example.com")
    r = api2.c.post("/api/v1/login/mfa", json={"mfa_token": t2, "code": totp_for(db, "mfa@example.com")}, headers={"Origin": ORIGIN})
    assert r.status_code == 401


def test_expired_challenge_rejected(db, enrolled):
    from datetime import datetime, timedelta, timezone

    api = Api()
    token = api.login("mfa@example.com").json()["mfa_token"]
    db.query(MFAChallenge).update({"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)})
    db.commit()
    r = api.c.post("/api/v1/login/mfa", json={"mfa_token": token, "code": totp_for(db, "mfa@example.com")}, headers={"Origin": ORIGIN})
    assert r.status_code == 401


def test_mfa_failures_lock_the_account(db, enrolled):
    api = Api()
    token = api.login("mfa@example.com").json()["mfa_token"]
    for _ in range(settings.MAX_LOGIN_ATTEMPTS):
        api.c.post("/api/v1/login/mfa", json={"mfa_token": token, "code": "111111"}, headers={"Origin": ORIGIN})
    r = Api().login("mfa@example.com")  # correct password, but locked
    assert r.status_code == 401 and r.json()["detail"] == "Invalid credentials"


def test_mfa_failures_count_toward_ip_throttle(db, enrolled):
    api = Api()
    for _ in range(settings.RATE_LIMIT_LOGIN_FAILURES):
        api.c.post("/api/v1/login/mfa", json={"mfa_token": "bogus", "code": "111111"}, headers={"Origin": ORIGIN})
    r = api.c.post("/api/v1/login/mfa", json={"mfa_token": "bogus", "code": "111111"}, headers={"Origin": ORIGIN})
    assert r.status_code == 429


def test_login_mfa_rejects_foreign_origin(db, enrolled):
    api = Api()
    token = api.login("mfa@example.com").json()["mfa_token"]
    r = api.c.post("/api/v1/login/mfa", json={"mfa_token": token, "code": "123456"}, headers={"Origin": "http://evil.example"})
    assert r.status_code == 403


def test_failed_mfa_is_audited(db, enrolled, admin):
    mfa_login(db, code="123456")
    assert admin.get("/admin/audit?action=MFA_CHALLENGE_FAILED").json()["total"] == 1


# ---- recovery codes -------------------------------------------------------------

def test_recovery_code_works_once(db, enrolled, admin):
    code = enrolled.codes[0]
    _, _, ok = mfa_login(db, code=code.lower())  # case-insensitive
    assert ok.status_code == 200
    _, _, again = mfa_login(db, code=code)
    assert again.status_code == 401
    assert admin.get("/admin/audit?action=MFA_RECOVERY_USED").json()["total"] == 1
    api, _, _ = mfa_login(db, code=enrolled.codes[1])
    assert api.get("/me/mfa").json()["recovery_codes_remaining"] == 8


def test_regenerate_recovery_codes_invalidates_old(db, enrolled):
    api, _, _ = mfa_login(db)
    reset_replay(db, "mfa@example.com")
    r = api.post("/me/mfa/recovery-codes", {"password": STRONG, "code": totp_for(db, "mfa@example.com")})
    assert r.status_code == 200 and len(r.json()["recovery_codes"]) == 10
    _, _, old = mfa_login(db, code=enrolled.codes[0])
    assert old.status_code == 401
    _, _, new = mfa_login(db, code=r.json()["recovery_codes"][0])
    assert new.status_code == 200


# ---- disable / admin reset ------------------------------------------------------

def test_disable_needs_password_and_code(db, enrolled):
    api, _, _ = mfa_login(db)
    reset_replay(db, "mfa@example.com")
    c = totp_for(db, "mfa@example.com")
    assert api.post("/me/mfa/disable", {"password": "WrongPassw0rd!!", "code": c}).status_code == 403
    assert api.post("/me/mfa/disable", {"password": STRONG, "code": "000000"}).status_code == 400
    assert api.get("/me/mfa").json()["enabled"] is True
    assert api.post("/me/mfa/disable", {"password": STRONG, "code": c}).status_code == 200
    assert api.get("/me/mfa").json()["enabled"] is False
    assert Api().login("mfa@example.com").json()["success"] is True  # no more second step
    assert db.query(MFARecoveryCode).count() == 0


def test_admin_can_reset_lost_device(db, enrolled, admin):
    uid = enrolled.user.id
    assert admin.post(f"/admin/users/{uid}/mfa/reset").status_code == 200
    assert enrolled.get("/me").status_code == 401  # sessions revoked
    assert Api().login("mfa@example.com").json()["success"] is True
    assert admin.post(f"/admin/users/{uid}/mfa/reset").status_code == 409  # nothing left to reset
    assert admin.get("/admin/audit?action=MFA_RESET").json()["total"] == 1


def test_admin_reset_follows_target_protections(db, admin, super_admin, member):
    assert admin.post(f"/admin/users/{super_admin.user.id}/mfa/reset").status_code == 403
    assert admin.post(f"/admin/users/{admin.user.id}/mfa/reset").status_code == 400
    assert member.post(f"/admin/users/{admin.user.id}/mfa/reset").status_code == 403  # non-admin


def test_mfa_cascades_on_user_delete(db, enrolled, admin):
    assert admin.delete(f"/admin/users/{enrolled.user.id}").status_code == 200
    assert db.query(UserMFA).count() == 0 and db.query(MFARecoveryCode).count() == 0


def test_super_admin_can_enrol_totp_and_must_use_it_to_sign_in(db, super_admin):
    """Admins and super admins use the same self-service enrolment as everyone else."""
    codes = enrol(super_admin, db, super_admin.user.email)
    assert len(codes) == 10

    fresh = Api()
    r = fresh.login(super_admin.user.email)
    assert r.status_code == 200 and r.json()["mfa_required"] is True
    assert "csrf_token" not in r.json()

    r = fresh.c.post(
        "/api/v1/login/mfa",
        json={"mfa_token": r.json()["mfa_token"], "code": totp_for(db, super_admin.user.email)},
        headers={"Origin": ORIGIN},
    )
    assert r.status_code == 200, r.text
    assert r.json()["user"]["is_super_admin"] is True
