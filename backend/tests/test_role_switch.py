"""Per-session 'user view' for administrators."""

from backend.app.audit.model import AuditAction, AuditEvent
from tests.conftest import STRONG, Api, make_user


def test_admin_can_work_as_a_normal_user_and_loses_admin_powers_server_side(super_admin):
    assert super_admin.get("/admin/users").status_code == 200
    r = super_admin.post("/me/role/user")
    assert r.status_code == 200 and r.json()["user"]["acting_as_user"] is True
    me = super_admin.get("/me").json()["user"]
    assert me["acting_as_user"] is True and me["is_super_admin"] is True  # still the same person

    for path in ("/admin/users", "/admin/stats", "/admin/audit"):
        r = super_admin.get(path)
        assert r.status_code == 403, path
        assert "admin view" in r.json()["detail"]
    assert super_admin.post("/admin/users", {"email": "x@example.com"}).status_code == 403
    # ordinary self-service keeps working
    assert super_admin.get("/me/profile").status_code == 200
    assert super_admin.get("/me/sessions").status_code == 200


def test_switching_back_needs_the_password(super_admin):
    super_admin.post("/me/role/user")
    r = super_admin.post("/me/role/admin", {"password": "WrongPassw0rd!!"})
    assert r.status_code == 403
    assert super_admin.get("/admin/users").status_code == 403  # still in user view
    r = super_admin.post("/me/role/admin", {"password": STRONG})
    assert r.status_code == 200 and r.json()["user"]["acting_as_user"] is False
    assert super_admin.get("/admin/users").status_code == 200


def test_user_view_is_per_session_not_per_account(db, admin):
    other = Api()
    assert other.login(admin.user.email).status_code == 200
    admin.post("/me/role/user")
    assert admin.get("/admin/users").status_code == 403
    assert other.get("/admin/users").status_code == 200  # the other device is untouched


def test_a_new_login_starts_in_admin_view(admin):
    admin.post("/me/role/user")
    fresh = Api()
    fresh.login(admin.user.email)
    assert fresh.get("/me").json()["user"]["acting_as_user"] is False
    assert fresh.get("/admin/users").status_code == 200


def test_plain_users_have_no_role_to_switch(member):
    assert member.post("/me/role/user").status_code == 400
    assert member.post("/me/role/admin", {"password": STRONG}).status_code == 400
    assert member.get("/me").json()["user"]["acting_as_user"] is False


def test_switching_requires_a_session_and_csrf(admin):
    assert Api().post("/me/role/user", csrf=False).status_code == 401
    assert admin.post("/me/role/user", csrf=False).status_code == 403
    assert admin.get("/admin/users").status_code == 200  # nothing changed


def test_wrong_passwords_hit_the_ip_throttle(db, admin):
    from backend.app.config import settings

    admin.post("/me/role/user")
    for _ in range(settings.RATE_LIMIT_LOGIN_FAILURES):
        admin.post("/me/role/admin", {"password": "WrongPassw0rd!!"})
    assert admin.post("/me/role/admin", {"password": STRONG}).status_code == 429


def test_switches_are_audited_and_idempotent(db, admin):
    admin.post("/me/role/user")
    admin.post("/me/role/user")  # no duplicate event
    admin.post("/me/role/admin", {"password": STRONG})
    db.expire_all()
    evs = db.query(AuditEvent).filter_by(action=AuditAction.ROLE_SWITCHED.value).order_by(AuditEvent.id).all()
    assert [e.event_metadata["to"] for e in evs] == ["user", "admin"]
    assert all(e.actor_id == str(admin.user.id) for e in evs)


def test_user_view_does_not_bypass_or_change_the_mfa_gate(monkeypatch, db, admin):
    from backend.app.config import settings

    monkeypatch.setattr(settings, "ADMIN_MFA_REQUIRED", True)
    admin.post("/me/role/user")
    # switching back does not lift the enrolment gate
    assert admin.post("/me/role/admin", {"password": STRONG}).status_code == 200
    assert admin.get("/admin/users").status_code == 403
    assert "setup required" in admin.get("/admin/users").json()["detail"]
