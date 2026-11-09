"""Administrator roles (ADR 014): enforced centrally, assigned only by super administrators, effective immediately."""

import pytest

from backend.app.admin_roles import permissions
from tests.conftest import make_user


def give(super_admin, admin, *roles):
    r = super_admin.put(f"/admin/roles/users/{admin.user.id}", {"roles": list(roles)})
    assert r.status_code == 200, r.text


def test_plain_admin_with_no_roles_keeps_full_access(admin):
    a = admin.get("/me/admin-access").json()
    assert a["implicit"] is True and a["roles"] == [] and a["access"]["users"] == "write"
    assert admin.get("/admin/users").status_code == 200
    assert admin.post("/admin/groups", {"name": "G"}).status_code in (200, 201)


def test_read_only_admin_reads_everything_and_changes_nothing(super_admin, admin):
    give(super_admin, admin, "read_only_admin")
    for path in ("/admin/users", "/admin/groups", "/admin/applications", "/admin/audit", "/admin/stats", "/admin/network-zones"):
        assert admin.get(path).status_code == 200, path
    r = admin.post("/admin/groups", {"name": "Nope"})
    assert r.status_code == 403 and "role does not allow" in r.json()["detail"]
    assert admin.post("/admin/applications", {"name": "x", "sign_on_mode": "none"}).status_code == 403
    assert admin.post("/admin/network-zones", {"name": "z", "cidrs": ["10.0.0.0/8"]}).status_code == 403


def test_help_desk_can_support_users_but_not_create_delete_or_reconfigure(db, super_admin, admin):
    give(super_admin, admin, "help_desk_admin")
    u = make_user(db, "needs.help@example.com")
    assert admin.patch(f"/admin/users/{u.id}", {"status": "suspended"}).status_code == 200
    assert admin.patch(f"/admin/users/{u.id}", {"status": "active"}).status_code == 200
    assert admin.post(f"/admin/users/{u.id}/password", {"new_password": "Brand-New-Passw0rd!x"}).status_code == 200
    assert admin.post("/admin/users", {"email": "new@example.com", "first_name": "N", "last_name": "U"}).status_code == 403
    assert admin.delete(f"/admin/users/{u.id}").status_code == 403
    assert admin.post("/admin/groups", {"name": "G"}).status_code == 403
    assert admin.post("/admin/applications", {"name": "x", "sign_on_mode": "none"}).status_code == 403
    assert admin.get("/admin/applications").status_code == 200       # may look
    assert admin.get("/admin/audit").status_code == 403              # reports are not theirs


def test_help_desk_still_cannot_touch_other_admins(db, super_admin, admin):
    give(super_admin, admin, "help_desk_admin")
    other = make_user(db, "other.admin@example.com", admin=True)
    assert admin.patch(f"/admin/users/{other.id}", {"status": "suspended"}).status_code == 403  # existing rule still applies


def test_app_admin_manages_applications_only(super_admin, admin):
    give(super_admin, admin, "app_admin")
    assert admin.post("/admin/applications", {"name": "Wiki", "sign_on_mode": "bookmark", "launch_url": "https://example.com/"}).status_code == 201
    assert admin.get("/admin/users").status_code == 200 and admin.get("/admin/groups").status_code == 200
    assert admin.post("/admin/groups", {"name": "G"}).status_code == 403
    assert admin.post("/admin/users/bulk", {"user_ids": [1], "action": "suspend"}).status_code == 403
    assert admin.get("/admin/audit").status_code == 403


def test_group_admin_manages_groups_only(super_admin, admin):
    give(super_admin, admin, "group_admin")
    assert admin.post("/admin/groups", {"name": "Team"}).status_code in (200, 201)
    assert admin.post("/admin/applications", {"name": "x", "sign_on_mode": "none"}).status_code == 403
    assert admin.post("/admin/network-zones", {"name": "z", "cidrs": ["10.0.0.0/8"]}).status_code == 403


def test_report_admin_reads_logs_only(super_admin, admin):
    give(super_admin, admin, "report_admin")
    assert admin.get("/admin/audit").status_code == 200 and admin.get("/admin/audit/export").status_code == 200
    assert admin.get("/admin/stats").status_code == 200 and admin.get("/admin/dashboard").status_code == 200
    assert admin.get("/admin/applications").status_code == 403
    assert admin.post("/admin/groups", {"name": "G"}).status_code == 403


def test_roles_combine_as_a_union(super_admin, admin):
    give(super_admin, admin, "app_admin", "group_admin")
    assert admin.post("/admin/groups", {"name": "Both"}).status_code in (200, 201)
    assert admin.post("/admin/applications", {"name": "Both", "sign_on_mode": "none"}).status_code == 201
    assert admin.post("/admin/network-zones", {"name": "z", "cidrs": ["10.0.0.0/8"]}).status_code == 403


def test_a_role_change_applies_to_the_very_next_request(super_admin, admin):
    assert admin.post("/admin/groups", {"name": "Before"}).status_code in (200, 201)
    give(super_admin, admin, "read_only_admin")
    assert admin.post("/admin/groups", {"name": "After"}).status_code == 403   # same session, no re-login
    give(super_admin, admin)                                                    # back to the default
    assert admin.post("/admin/groups", {"name": "After"}).status_code in (200, 201)


def test_only_super_admins_manage_roles(db, super_admin, admin, member):
    assert admin.get("/admin/roles").status_code == 403
    assert admin.put(f"/admin/roles/users/{admin.user.id}", {"roles": ["org_admin"]}).status_code == 403  # no self-service either
    assert member.get("/admin/roles").status_code == 403
    cat = super_admin.get("/admin/roles").json()["items"]
    assert {c["id"] for c in cat} == set(permissions.ROLE_IDS)


def test_role_assignment_rules_and_audit(db, super_admin, admin):
    assert super_admin.put(f"/admin/roles/users/{admin.user.id}", {"roles": ["nope"]}).status_code == 400
    plain = make_user(db, "plain@example.com")
    assert super_admin.put(f"/admin/roles/users/{plain.id}", {"roles": ["app_admin"]}).status_code == 400   # not an administrator
    assert super_admin.put(f"/admin/roles/users/{super_admin.user.id}", {"roles": ["app_admin"]}).status_code == 400
    assert super_admin.put("/admin/roles/users/999999", {"roles": []}).status_code == 404
    give(super_admin, admin, "app_admin")
    got = super_admin.get(f"/admin/roles/users/{admin.user.id}").json()
    assert got["roles"] == ["app_admin"] and got["implicit"] is False
    ev = super_admin.get("/admin/audit?action=ADMIN_ROLES_UPDATED").json()["items"]
    assert ev and ev[0]["metadata"]["to"] == ["app_admin"]


def test_super_admin_is_never_restricted(super_admin):
    a = super_admin.get("/me/admin-access").json()
    assert a["super_admin"] is True and a["access"]["roles"] == "write"
    assert super_admin.post("/admin/groups", {"name": "Root"}).status_code in (200, 201)


def test_unclassified_routes_need_a_super_admin():
    assert permissions.allowed(["org_admin"], "GET", "/admin/something-new") is False
    assert permissions.allowed([], "GET", "/admin/roles") is False
    assert permissions.area_for("/admin/users/{user_id}/mfa/reset") == "users"
    assert permissions.area_for("/admin/applications/{app_id}/policy") == "applications"


def test_non_admin_has_no_admin_access(member):
    assert member.get("/me/admin-access").status_code == 403
