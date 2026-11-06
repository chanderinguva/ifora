"""Admins must have a second factor before the admin API works for them."""

import pytest

from backend.app.config import settings
from tests.conftest import Api, STRONG, make_user
from tests.test_mfa import enrol
from tests.test_passkeys import register


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
    enrol(admin, db, admin.user.email)
    assert admin.get("/me").json()["user"]["mfa_setup_required"] is False
    assert admin.get("/admin/users").status_code == 200


def test_enrolled_admin_passes_after_mfa_login(db, admin):
    enrol(admin, db, admin.user.email)
    from tests.test_mfa import mfa_login

    s, _, r2 = mfa_login(db, admin.user.email)
    assert r2.status_code == 200
    assert s.get("/admin/users").status_code == 200


def test_a_passkey_also_satisfies_the_policy(admin):
    _, r = register(admin)
    assert r.status_code == 201, r.text
    assert admin.get("/admin/users").status_code == 200


def test_disabling_mfa_regates_the_admin(db, admin):
    codes = enrol(admin, db, admin.user.email)
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
