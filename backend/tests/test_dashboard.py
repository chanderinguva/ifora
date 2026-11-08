"""Admin dashboard: attention tasks and trends are computed from live data and are admin-only."""

from tests.conftest import make_user


def _tasks(admin):
    return {t["id"]: t for t in admin.get("/admin/dashboard").json()["tasks"]}


def test_dashboard_shape_and_admin_only(admin, member):
    d = admin.get("/admin/dashboard").json()
    assert set(d) == {"tasks", "signins", "users_by_status", "apps_by_mode", "apps_total"}
    assert len(d["signins"]) == 7 and all({"date", "success", "failure"} <= set(x) for x in d["signins"])
    assert member.get("/admin/dashboard").status_code == 403


def test_signins_count_todays_logins(admin):
    today = admin.get("/admin/dashboard").json()["signins"][-1]
    assert today["success"] >= 1


def test_admin_without_second_factor_is_a_high_task(admin):
    t = _tasks(admin)["admins_no_mfa"]
    assert t["severity"] == "high" and t["count"] >= 1 and t["href"] == "/admin/users"


def test_locked_out_and_expired_and_staged_users_become_tasks(db, admin):
    for email, status in (("lo@example.com", "locked_out"), ("pe@example.com", "password_expired"), ("st@example.com", "staged")):
        u = make_user(db, email)
        u.status = status
    db.commit()
    t = _tasks(admin)
    assert t["locked_out"]["count"] == 1 and t["password_expired"]["count"] == 1 and t["awaiting_activation"]["count"] == 1
    assert t["awaiting_activation"]["severity"] == "info"
    by = admin.get("/admin/dashboard").json()["users_by_status"]
    assert by["locked_out"] == 1 and by["staged"] == 1


def test_unassigned_application_is_a_task_until_someone_is_assigned(db, admin):
    a = admin.post("/admin/applications", {"name": "Lonely", "sign_on_mode": "bookmark", "launch_url": "https://example.com/"}).json()
    assert _tasks(admin)["apps_unassigned"]["count"] == 1
    u = make_user(db, "assignee@example.com")
    admin.post(f"/admin/applications/{a['id']}/assignments", {"user_id": u.id})
    assert "apps_unassigned" not in _tasks(admin)
    assert admin.get("/admin/dashboard").json()["apps_by_mode"]["bookmark"] == 1


def test_provisioning_only_apps_are_not_flagged_unassigned(admin):
    admin.post("/admin/applications", {"name": "Prov only", "sign_on_mode": "none"})
    assert "apps_unassigned" not in _tasks(admin)


def test_failed_login_alert_needs_a_real_spike(db, admin):
    from backend.app.audit.model import AuditAction
    from backend.app.audit.service import record

    for _ in range(9):
        record(db, AuditAction.LOGIN_FAILURE, None, None, None, "user", {})
    db.commit()
    assert "failed_logins" not in _tasks(admin)
    record(db, AuditAction.LOGIN_FAILURE, None, None, None, "user", {})
    db.commit()
    t = _tasks(admin)["failed_logins"]
    assert t["count"] == 10 and t["severity"] == "high"
