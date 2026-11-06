"""Admins must have a second factor before the admin API works for them."""

import pytest

from datetime import timedelta

from backend.app.audit.model import AuditAction, AuditEvent
from backend.app.auth import mfa_service
from backend.app.config import settings
from backend.app.users.model import User
from backend.cli import main as cli_main
from tests.conftest import Api, STRONG, make_user
from tests.test_mfa import enrol
from tests.test_passkeys import register


def give_code(db, user):
    """What an operator or super admin does: issue a one-time enrolment code."""
    u = db.get(User, user.id)
    code = mfa_service.issue_enrollment_code(u)
    db.commit()
    return code


@pytest.fixture(autouse=True)
def policy_on(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_MFA_REQUIRED", True)


def test_admin_without_second_factor_can_sign_in_but_not_administer(admin):
    me = admin.get("/me").json()["user"]
    assert me["mfa_setup_required"] is True
    r = admin.get("/admin/users")
    assert r.status_code == 403 and "setup required" in r.json()["detail"]
    assert admin.get("/admin/stats").status_code == 403
    assert admin.post("/admin/users", {"email": "x@example.com"}).status_code == 403


def test_super_admin_is_gated_too(super_admin):
    assert super_admin.get("/admin/users").status_code == 403


def test_gated_admin_can_still_reach_self_service_to_enrol(db, admin):
    assert admin.get("/me/profile").status_code == 200
    enrol(admin, db, admin.user.email, give_code(db, admin.user))
    assert admin.get("/me").json()["user"]["mfa_setup_required"] is False
    assert admin.get("/admin/users").status_code == 200


def test_enrolled_admin_passes_after_mfa_login(db, admin):
    enrol(admin, db, admin.user.email, give_code(db, admin.user))
    from tests.test_mfa import mfa_login

    s, _, r2 = mfa_login(db, admin.user.email)
    assert r2.status_code == 200
    assert s.get("/admin/users").status_code == 200


def test_a_passkey_also_satisfies_the_policy(db, admin):
    _, r = register(admin, enrollment_code=give_code(db, admin.user))
    assert r.status_code == 201, r.text
    assert admin.get("/admin/users").status_code == 200


def test_disabling_mfa_regates_the_admin(db, admin):
    codes = enrol(admin, db, admin.user.email, give_code(db, admin.user))
    assert admin.get("/admin/users").status_code == 200
    r = admin.post("/me/mfa/disable", {"password": STRONG, "code": codes[0]})
    assert r.status_code == 200, r.text
    assert admin.get("/admin/users").status_code == 403


def test_normal_users_are_unaffected(member):
    assert member.get("/me").json()["user"]["mfa_setup_required"] is False
    assert member.get("/me/profile").status_code == 200


def test_policy_can_be_switched_off(monkeypatch, admin):
    monkeypatch.setattr(settings, "ADMIN_MFA_REQUIRED", False)
    assert admin.get("/admin/users").status_code == 200


# ---- the enrolment code: a password alone must not be enough to attach a first factor ----------

def test_password_alone_cannot_enrol_totp_or_a_passkey(admin):
    r = admin.post("/me/mfa/setup", {"password": STRONG})
    assert r.status_code == 403 and "enrolment code" in r.json()["detail"]
    _, r = register_raw(admin, None)
    assert r.status_code == 403
    assert admin.get("/admin/users").status_code == 403


def register_raw(api, code):
    return None, api.post("/me/passkeys/register/options", {"password": STRONG, "enrollment_code": code})


def test_wrong_code_is_refused_and_does_not_burn_the_real_one(db, admin):
    good = give_code(db, admin.user)
    assert admin.post("/me/mfa/setup", {"password": STRONG, "enrollment_code": "AAAA-BBBB-CCCC"}).status_code == 403
    assert admin.post("/me/mfa/setup", {"password": STRONG, "enrollment_code": good}).status_code == 200


def test_code_format_is_forgiving_but_wrong_password_still_fails(db, admin):
    code = give_code(db, admin.user)
    assert admin.post("/me/mfa/setup", {"password": "WrongPassw0rd!!", "enrollment_code": code}).status_code == 403
    assert admin.post("/me/mfa/setup", {"password": STRONG, "enrollment_code": code.lower().replace("-", " ")}).status_code == 200


def test_code_is_single_use(db, admin):
    code = give_code(db, admin.user)
    codes = enrol(admin, db, admin.user.email, code)
    # lose the factor again: the old code must not work any more
    admin.post("/me/mfa/disable", {"password": STRONG, "code": codes[0]})
    assert admin.post("/me/mfa/setup", {"password": STRONG, "enrollment_code": code}).status_code == 403


def test_expired_code_is_refused(db, admin):
    code = give_code(db, admin.user)
    u = db.get(User, admin.user.id)
    u.enrollment_code_expires_at = u.enrollment_code_expires_at - timedelta(hours=25)
    db.commit()
    assert admin.post("/me/mfa/setup", {"password": STRONG, "enrollment_code": code}).status_code == 403


def test_a_new_code_replaces_the_old_one(db, admin):
    old = give_code(db, admin.user)
    new = give_code(db, admin.user)
    assert admin.post("/me/mfa/setup", {"password": STRONG, "enrollment_code": old}).status_code == 403
    assert admin.post("/me/mfa/setup", {"password": STRONG, "enrollment_code": new}).status_code == 200


def test_only_a_hash_is_stored(db, admin):
    code = give_code(db, admin.user)
    u = db.get(User, admin.user.id)
    assert code.replace("-", "") not in (u.enrollment_code_hash or "")
    assert len(u.enrollment_code_hash) == 64


def test_admin_who_already_has_a_factor_does_not_need_a_code_to_add_another(db, admin):
    enrol(admin, db, admin.user.email, give_code(db, admin.user))
    _, r = register(admin)
    assert r.status_code == 201, r.text


def test_normal_users_never_need_a_code(member):
    assert member.post("/me/mfa/setup", {"password": STRONG}).status_code == 200


def test_wrong_codes_hit_the_ip_throttle(db, admin):
    for _ in range(settings.RATE_LIMIT_LOGIN_FAILURES):
        admin.post("/me/mfa/setup", {"password": STRONG, "enrollment_code": "AAAA-BBBB-CCCC"})
    good = give_code(db, admin.user)
    assert admin.post("/me/mfa/setup", {"password": STRONG, "enrollment_code": good}).status_code == 429


def test_super_admin_issues_a_code_for_an_admin(db, super_admin):
    target = make_user(db, "newadmin@example.com", admin=True)
    # the issuing super admin must themselves be enrolled
    enrol(super_admin, db, super_admin.user.email, give_code(db, super_admin.user))
    r = super_admin.post(f"/admin/users/{target.id}/enrollment-code")
    assert r.status_code == 200, r.text
    code = r.json()["code"]

    a = Api()
    assert a.login(target.email).status_code == 200
    assert a.post("/me/mfa/setup", {"password": STRONG, "enrollment_code": code}).status_code == 200
    db.expire_all()
    ev = db.query(AuditEvent).filter_by(action=AuditAction.ENROLLMENT_CODE_ISSUED.value).one()
    assert ev.target_id == str(target.id)
    assert code.replace("-", "") not in str(ev.event_metadata)


def test_plain_admin_cannot_issue_codes_and_super_admin_codes_are_cli_only(db, admin, super_admin):
    other = make_user(db, "other@example.com", admin=True)
    enrol(admin, db, admin.user.email, give_code(db, admin.user))
    assert admin.post(f"/admin/users/{other.id}/enrollment-code").status_code == 403
    enrol(super_admin, db, super_admin.user.email, give_code(db, super_admin.user))
    assert super_admin.post(f"/admin/users/{super_admin.user.id}/enrollment-code").status_code == 400
    plain = make_user(db, "plain@example.com")
    assert super_admin.post(f"/admin/users/{plain.id}/enrollment-code").status_code == 400


def test_no_code_for_an_admin_who_already_has_a_factor(db, super_admin):
    enrol(super_admin, db, super_admin.user.email, give_code(db, super_admin.user))
    target = make_user(db, "enrolled@example.com", admin=True)
    a = Api()
    a.login(target.email)
    enrol(a, db, target.email, give_code(db, target))
    assert super_admin.post(f"/admin/users/{target.id}/enrollment-code").status_code == 409


def test_cli_issues_a_working_code(db, admin, capsys):
    assert cli_main(["issue-enrollment-code", admin.user.email]) == 0
    code = [l.strip() for l in capsys.readouterr().out.splitlines() if l.strip()][1]
    assert admin.post("/me/mfa/setup", {"password": STRONG, "enrollment_code": code}).status_code == 200
    db.expire_all()
    ev = db.query(AuditEvent).filter_by(action=AuditAction.ENROLLMENT_CODE_ISSUED.value).one()
    assert ev.actor_id is None and ev.event_metadata["via"] == "cli"


def test_cli_refuses_non_admins_and_unknown_users(db, member):
    assert cli_main(["issue-enrollment-code", "member@example.com"]) == 1
    assert cli_main(["issue-enrollment-code", "nobody@example.com"]) == 1
