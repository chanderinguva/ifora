"""Admin user management and RBAC."""

import pytest

from tests.conftest import STRONG, Api, make_user

NEW = {"email": "new@example.com", "first_name": "New", "last_name": "Person", "password": STRONG}

ADMIN_ENDPOINTS = [
    ("get", "/admin/users"),
    ("post", "/admin/users"),
    ("get", "/admin/users/1"),
    ("patch", "/admin/users/1"),
    ("delete", "/admin/users/1"),
    ("post", "/admin/users/1/password"),
    ("get", "/admin/groups"),
    ("post", "/admin/groups"),
    ("get", "/admin/audit"),
    ("get", "/admin/stats"),
]


@pytest.mark.parametrize("method,url", ADMIN_ENDPOINTS)
def test_admin_endpoints_deny_anonymous_and_non_admin(method, url, anon, member):
    assert getattr(anon, method)(url).status_code == 401
    assert getattr(member, method)(url).status_code == 403


def test_create_get_list_update_delete(admin):
    r = admin.post("/admin/users", NEW)
    assert r.status_code == 201, r.text
    u = r.json()
    assert u["username"] == "new.person" and "password" not in u and "password_hash" not in u
    uid = u["id"]
    assert admin.get(f"/admin/users/{uid}").json()["email"] == "new@example.com"
    assert admin.get("/admin/users?q=person").json()["total"] == 1
    r = admin.patch(f"/admin/users/{uid}", {"first_name": "Renamed", "profile_attributes": {"department": "IT"}})
    assert r.json()["first_name"] == "Renamed" and r.json()["profile_attributes"] == {"department": "IT"}
    assert admin.delete(f"/admin/users/{uid}").status_code == 200
    assert admin.get(f"/admin/users/{uid}").status_code == 404


def test_new_user_can_log_in(admin):
    admin.post("/admin/users", NEW)
    assert Api().login("new@example.com", STRONG).status_code == 200


def test_validation(admin):
    assert admin.post("/admin/users", {**NEW, "password": "short"}).status_code == 422
    assert admin.post("/admin/users", {**NEW, "password": "alllowercase123456"}).status_code == 422
    assert admin.post("/admin/users", {**NEW, "email": "not-an-email"}).status_code == 422
    assert admin.post("/admin/users", {**NEW, "profile_attributes": {"Bad Key": "x"}}).status_code == 422
    r = admin.post("/admin/users", {**NEW, "password": "short"})
    assert "short" not in r.text  # validation errors must not echo the password


def test_duplicate_email_and_username(admin):
    assert admin.post("/admin/users", NEW).status_code == 201
    assert admin.post("/admin/users", {**NEW, "email": "NEW@example.com"}).status_code == 409
    assert admin.post("/admin/users", {**NEW, "email": "x@example.com", "username": "new.person"}).status_code == 409
    r = admin.post("/admin/users", {**NEW, "email": "new@other.org"})  # derived username collides -> suffixed
    assert r.status_code == 201 and r.json()["username"] == "new.person2"


def test_mutations_require_csrf(admin):
    assert admin.post("/admin/users", NEW, csrf=False).status_code == 403


def test_pagination_bounds(admin):
    assert admin.get("/admin/users?page_size=1000").status_code == 422
    assert admin.get("/admin/users?page=0").status_code == 422


def test_admin_cannot_grant_or_touch_admins(admin, super_admin, db):
    assert admin.post("/admin/users", {**NEW, "is_admin": True}).status_code == 403
    other = make_user(db, "other-admin@example.com", admin=True)
    assert admin.patch(f"/admin/users/{other.id}", {"first_name": "X"}).status_code == 403
    assert admin.delete(f"/admin/users/{other.id}").status_code == 403
    assert admin.post(f"/admin/users/{other.id}/password", {"new_password": STRONG + "1"}).status_code == 403
    plain = make_user(db, "plain@example.com")
    assert admin.patch(f"/admin/users/{plain.id}", {"is_admin": True}).status_code == 403
    assert super_admin.patch(f"/admin/users/{plain.id}", {"is_admin": True}).status_code == 200


def test_super_admin_is_protected_and_no_self_harm(admin, super_admin):
    root = super_admin.user.id
    assert admin.delete(f"/admin/users/{root}").status_code == 403
    assert admin.patch(f"/admin/users/{root}", {"status": "deprovisioned"}).status_code == 403
    assert super_admin.delete(f"/admin/users/{root}").status_code == 400
    assert super_admin.patch(f"/admin/users/{root}", {"status": "deprovisioned"}).status_code == 400
    assert admin.delete(f"/admin/users/{admin.user.id}").status_code == 400
    assert admin.patch(f"/admin/users/{admin.user.id}", {"status": "deprovisioned"}).status_code == 400


def test_mass_assignment_ignored(admin, db):
    plain = make_user(db, "plain@example.com")
    r = admin.patch(f"/admin/users/{plain.id}", {"is_super_admin": True, "password_hash": "x"})
    assert r.status_code == 200 and r.json()["is_super_admin"] is False


def test_deactivate_revokes_sessions(admin, member):
    assert member.get("/me").status_code == 200
    assert admin.patch(f"/admin/users/{member.user.id}", {"status": "deprovisioned"}).status_code == 200
    assert member.get("/me").status_code == 401
    assert admin.patch(f"/admin/users/{member.user.id}", {"status": "active"}).status_code == 200
    assert Api().login("member@example.com").status_code == 200


def test_admin_password_reset(admin, member):
    new = "Different1Passw0rd"
    assert admin.post(f"/admin/users/{member.user.id}/password", {"new_password": new}).status_code == 200
    assert member.get("/me").status_code == 401
    assert Api().login("member@example.com", STRONG).status_code == 401
    assert Api().login("member@example.com", new).status_code == 200


def test_demotion_revokes_sessions(super_admin, db):
    u = make_user(db, "second@example.com", admin=True)
    a = Api()
    a.login(u.email)
    assert a.get("/admin/stats").status_code == 200
    assert super_admin.patch(f"/admin/users/{u.id}", {"is_admin": False}).status_code == 200
    assert a.get("/admin/stats").status_code == 401
