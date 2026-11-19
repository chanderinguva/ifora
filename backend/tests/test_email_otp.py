"""Email one-time code second factor (IFORA-60): enrolment, login, expiry, attempt limit and cooldown, throttling, policy, reset."""

import re
from datetime import datetime, timedelta, timezone

import pytest

from backend.app import mailer
from backend.app.auth.mfa_model import UserEmailOTP
from backend.app.config import settings
from backend.app.users.model import User
from tests.conftest import ORIGIN, STRONG, Api, make_user


@pytest.fixture
def sent(monkeypatch):
    box = []
    monkeypatch.setitem(mailer.overrides, "send", box.append)
    return box


def no_mail(monkeypatch):
    """A server with no outgoing mail at all (the test environment may have SMTP settings of its own)."""
    mailer.overrides.pop("send", None)
    monkeypatch.setattr(settings, "SMTP_HOST", "")


def code_of(msg) -> str:
    m = re.search(r"\b(\d{6})\b", msg["Subject"])
    assert m, msg["Subject"]
    return m.group(1)


def set_policy(sa, **over):
    cur = sa.get("/admin/security-policy").json()["policy"]
    r = sa.put("/admin/security-policy", {**cur, **over})
    assert r.status_code == 200, r.text
    return r.json()


def enrol(api, sent, password=STRONG):
    assert api.post("/me/mfa/email/setup", {"password": password}).status_code == 200
    code = code_of(sent[-1])
    r = api.post("/me/mfa/email/enable", {"code": code})
    assert r.status_code == 200, r.text
    return code


@pytest.fixture
def enrolled(db, super_admin, sent):
    set_policy(super_admin, email_otp_members="allowed")
    u = make_user(db, "otp@example.com")
    a = Api()
    assert a.login(u.email).status_code == 200
    a.user = u
    enrol(a, sent)
    sent.clear()
    return a


def step1(email="otp@example.com"):
    api = Api()
    r = api.login(email)
    assert r.status_code == 200 and r.json()["mfa_required"] is True, r.text
    return api, r.json()


def send_code(api, token):
    return api.c.post("/api/v1/login/mfa/email/send", json={"mfa_token": token}, headers={"Origin": ORIGIN})


def finish(api, token, code):
    r = api.c.post("/api/v1/login/mfa", json={"mfa_token": token, "code": code, "factor": "email"}, headers={"Origin": ORIGIN})
    if r.status_code == 200:
        api.csrf = r.json()["csrf_token"]
    return r


def row(db, email="otp@example.com") -> UserEmailOTP:
    db.expire_all()
    return db.query(UserEmailOTP).join(User, User.id == UserEmailOTP.user_id).filter(User.email == email).one()


# ---- policy and enrolment ---------------------------------------------------------------------------------------

def test_off_by_default_nobody_can_enrol(db, member, sent):
    assert member.get("/me/mfa/email").json()["allowed"] is False
    assert member.post("/me/mfa/email/setup", {"password": STRONG}).status_code == 403
    assert sent == []


def test_enrolment_needs_the_password_and_a_working_mail_server(db, super_admin, member, sent, monkeypatch):
    set_policy(super_admin, email_otp_members="allowed")
    assert member.post("/me/mfa/email/setup", {"password": "WrongPassw0rd!!"}).status_code == 403 and sent == []
    no_mail(monkeypatch)
    assert member.post("/me/mfa/email/setup", {"password": STRONG}).status_code == 503


def test_enrol_sends_a_six_digit_code_to_the_account_address_only(db, super_admin, member, sent):
    set_policy(super_admin, email_otp_members="allowed")
    assert member.post("/me/mfa/email/setup", {"password": STRONG}).json() == {"sent": True, "expires_in": 300}
    assert len(sent) == 1 and sent[0]["To"] == "member@example.com"
    code = code_of(sent[0])
    assert re.fullmatch(r"\d{6}", code) and code not in str(member.get("/me/mfa/email").json())
    r = row(db, "member@example.com")
    assert r.code_hash and code not in r.code_hash and r.enabled is False
    assert timedelta(seconds=290) < r.code_expires_at - datetime.now(timezone.utc) <= timedelta(seconds=300)
    assert member.post("/me/mfa/email/enable", {"code": "000000" if code != "000000" else "111111"}).status_code == 400
    assert member.post("/me/mfa/email/enable", {"code": code}).json() == {"enabled": True}
    assert member.get("/me/mfa/email").json()["enabled"] is True
    assert member.post("/me/mfa/email/setup", {"password": STRONG}).status_code == 409


def test_wrong_codes_while_enrolling_lock_it_after_three(db, super_admin, member, sent):
    set_policy(super_admin, email_otp_members="allowed")
    member.post("/me/mfa/email/setup", {"password": STRONG})
    good = code_of(sent[0])
    bad = "000000" if good != "000000" else "111111"
    assert [member.post("/me/mfa/email/enable", {"code": bad}).status_code for _ in range(3)] == [400, 400, 400]
    assert member.post("/me/mfa/email/enable", {"code": good}).status_code == 400          # the code was destroyed
    assert member.post("/me/mfa/email/setup", {"password": STRONG}).status_code == 429     # cooldown


# ---- login ------------------------------------------------------------------------------------------------------

def test_login_with_email_code_completes_and_is_not_recorded_as_mfa(db, enrolled, sent):
    api, body = step1()
    assert body["factors"] == ["email"]
    assert send_code(api, body["mfa_token"]).json() == {"sent": True, "expires_in": 300}
    assert sent[-1]["To"] == "otp@example.com"
    r = finish(api, body["mfa_token"], code_of(sent[-1]))
    assert r.status_code == 200, r.text
    from backend.app.auth.authn import acr_for
    from backend.app.auth.session import Session as AuthSession

    db.expire_all()
    amr = db.query(AuthSession).join(User, User.id == AuthSession.user_id).filter(User.email == "otp@example.com").order_by(AuthSession.id.desc()).first().amr
    assert "mfa" not in amr and "otp" in amr and acr_for(amr).endswith(":1")        # never an admin step-up proof, never acr 2


def test_a_code_works_once(db, enrolled, sent):
    api, body = step1()
    send_code(api, body["mfa_token"])
    code = code_of(sent[-1])
    assert finish(api, body["mfa_token"], code).status_code == 200
    api2, body2 = step1()
    assert finish(api2, body2["mfa_token"], code).status_code == 401


def test_expired_code_is_refused(db, enrolled, sent):
    api, body = step1()
    send_code(api, body["mfa_token"])
    r = row(db)
    r.code_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    assert finish(api, body["mfa_token"], code_of(sent[-1])).status_code == 401


def test_three_wrong_attempts_invalidate_the_code_and_start_a_cooldown(db, enrolled, sent):
    api, body = step1()
    send_code(api, body["mfa_token"])
    good = code_of(sent[-1])
    bad = "000000" if good != "000000" else "111111"
    assert [finish(api, body["mfa_token"], bad).status_code for _ in range(3)] == [401, 401, 401]
    assert row(db).code_hash is None and row(db).locked_until is not None
    assert finish(api, body["mfa_token"], good).status_code == 401                          # even the right code is dead now
    assert send_code(api, body["mfa_token"]).status_code == 429                              # and no new one during the cooldown
    assert len(sent) == 1


def test_non_digit_or_wrong_length_codes_never_match(db, enrolled, sent):
    api, body = step1()
    send_code(api, body["mfa_token"])
    for junk in ("", "12345", "1234567", "abcdef", "12 456", "١٢٣٤٥٦"):
        assert finish(api, body["mfa_token"], junk).status_code == 401


def test_requesting_codes_is_limited_to_three_a_minute(db, enrolled, sent):
    api, body = step1()
    # the enrolment mail (before `sent` was cleared) used one of this minute's three requests for the account
    assert [send_code(api, body["mfa_token"]).status_code for _ in range(2)] == [200, 200]
    assert send_code(api, body["mfa_token"]).status_code == 429
    assert len(sent) == 2


def test_send_needs_a_live_challenge_and_an_enrolled_allowed_factor(db, super_admin, enrolled, sent):
    assert send_code(Api(), "nope").status_code == 401
    api, body = step1()
    set_policy(super_admin, email_otp_members="off")                                          # switched off: the factor stops working
    assert send_code(api, body["mfa_token"]).status_code == 401
    assert Api().login("otp@example.com").json().get("mfa_required") is not True              # and login falls back to password only


def test_email_factor_cannot_be_used_without_asking_for_it(db, enrolled, sent):
    api, body = step1()
    send_code(api, body["mfa_token"])
    r = api.c.post("/api/v1/login/mfa", json={"mfa_token": body["mfa_token"], "code": code_of(sent[-1])}, headers={"Origin": ORIGIN})
    assert r.status_code == 401                                                               # the default path is app/recovery codes only


# ---- disable, reset, policy -------------------------------------------------------------------------------------

def test_disable_needs_the_password(db, enrolled, sent):
    assert enrolled.post("/me/mfa/email/disable", {"password": "WrongPassw0rd!!"}).status_code == 403
    assert enrolled.post("/me/mfa/email/disable", {"password": STRONG}).json() == {"enabled": False}
    assert enrolled.get("/me/mfa/email").json()["enabled"] is False


def test_admin_reset_removes_the_email_factor(db, super_admin, enrolled):
    uid = db.query(User).filter_by(email="otp@example.com").one().id
    assert super_admin.post(f"/admin/users/{uid}/mfa/reset").status_code == 200
    db.expire_all()
    assert db.query(UserEmailOTP).filter_by(user_id=uid).count() == 0
    assert Api().login("otp@example.com").json().get("mfa_required") is not True


def test_policy_requires_mail_and_keeps_unsent_fields(db, super_admin, sent, monkeypatch):
    cur = super_admin.get("/admin/security-policy").json()["policy"]
    no_mail(monkeypatch)
    assert super_admin.put("/admin/security-policy", {**cur, "email_otp_admins": "required"}).status_code == 422
    mailer.overrides["send"] = sent.append
    assert super_admin.put("/admin/security-policy", {**cur, "email_otp_members": "required"}).status_code == 422  # members: off | allowed
    set_policy(super_admin, email_otp_members="allowed")
    body = {k: v for k, v in super_admin.get("/admin/security-policy").json()["policy"].items() if not k.startswith("email_otp")}
    out = super_admin.put("/admin/security-policy", body).json()["policy"]               # an older client that omits the fields
    assert out["email_otp_members"] == "allowed" and out["email_otp_admins"] == "off"


def test_required_for_admins_blocks_admin_functions_until_enrolled(db, super_admin, admin, sent):
    assert admin.get("/admin/users").status_code == 200
    set_policy(super_admin, email_otp_admins="required")
    r = admin.get("/admin/users")
    assert r.status_code == 403 and "setup required" in r.json()["detail"]
    assert admin.get("/me").status_code == 200                                                 # own account stays reachable
    assert admin.get("/admin/security-policy").status_code == 200                              # an admin can always reach (and undo) the policy
    enrol(admin, sent)
    assert admin.get("/admin/users").status_code == 200
    assert admin.post("/me/mfa/email/disable", {"password": STRONG}).status_code == 409        # cannot opt out while required


def test_required_is_not_enforced_when_no_mail_can_be_sent(db, super_admin, admin, sent, monkeypatch):
    set_policy(super_admin, email_otp_admins="required")
    assert admin.get("/admin/users").status_code == 403
    no_mail(monkeypatch)
    assert admin.get("/admin/users").status_code == 200                                        # never lock admins out of a server that cannot send
