"""Self-service profile/password, audit trail and stats."""

from tests.conftest import STRONG, Api, make_user


def test_profile_read_and_update(member):
    p = member.get("/me/profile").json()
    assert p["email"] == "member@example.com" and "title" in p["editable_attributes"]
    r = member.patch("/me/profile", {"first_name": "Mia", "profile_attributes": {"title": "Dev", "phone": "123"}})
    assert r.status_code == 200 and r.json()["profile_attributes"] == {"title": "Dev", "phone": "123"}


def test_user_cannot_edit_admin_managed_attributes(member, admin):
    assert member.patch("/me/profile", {"profile_attributes": {"department": "Finance"}}).status_code == 403
    admin.patch(f"/admin/users/{member.user.id}", {"profile_attributes": {"department": "IT"}})
    member.patch("/me/profile", {"profile_attributes": {"title": "Dev"}})
    attrs = member.get("/me/profile").json()["profile_attributes"]
    assert attrs == {"department": "IT", "title": "Dev"}  # admin-managed key survived


def test_profile_cannot_change_privileges(member):
    r = member.patch("/me/profile", {"is_admin": True, "status": "inactive", "email": "x@y.com"})
    p = member.get("/me/profile").json()
    assert p["is_admin"] is False and p["status"] == "active" and p["email"] == "member@example.com"


def test_change_password(member):
    other = Api()
    other.login("member@example.com")
    assert member.post("/me/password", {"current_password": "nope", "new_password": "Another1Passw0rd"}).status_code == 403
    assert member.post("/me/password", {"current_password": STRONG, "new_password": "weak"}).status_code == 422
    r = member.post("/me/password", {"current_password": STRONG, "new_password": "Another1Passw0rd"})
    assert r.status_code == 200 and r.json()["other_sessions_revoked"] == 1
    assert member.get("/me").status_code == 200  # current session survives
    assert other.get("/me").status_code == 401  # other sessions do not
    assert Api().login("member@example.com", "Another1Passw0rd").status_code == 200


def test_my_sessions(member):
    s = member.get("/me/sessions").json()["items"]
    assert len(s) == 1 and s[0]["current"] is True


def test_audit_trail_records_actions_without_secrets(admin):
    admin.post("/admin/users", {"email": "n@example.com", "first_name": "N", "last_name": "N", "password": STRONG})
    gid = admin.post("/admin/groups", {"name": "G"}).json()["id"]
    admin.delete(f"/admin/groups/{gid}")
    ev = admin.get("/admin/audit?page_size=100").json()
    actions = [e["action"] for e in ev["items"]]
    for a in ("LOGIN_SUCCESS", "USER_CREATED", "GROUP_CREATED", "GROUP_DELETED"):
        assert a in actions
    created = admin.get("/admin/audit?action=USER_CREATED").json()["items"][0]
    assert created["actor_email"] == "admin@example.com" and created["target_type"] == "user"
    assert STRONG not in str(ev)
    assert admin.get("/admin/audit?action=BOGUS").status_code == 422


def test_failed_login_is_audited(db, admin):
    make_user(db, "v@example.com")
    Api().login("v@example.com", "WrongPassw0rd!!")
    assert admin.get("/admin/audit?action=LOGIN_FAILURE").json()["total"] == 1


def test_stats_are_real(admin, db):
    make_user(db, "a@example.com")
    gid = admin.post("/admin/groups", {"name": "G"}).json()["id"]
    admin.post(f"/admin/groups/{gid}/members", {"user_id": 2})
    s = admin.get("/admin/stats").json()
    assert s["users_total"] == 2 and s["groups"] == 1 and s["memberships"] == 1
    assert s["active_sessions"] == 1 and s["admins"] == 1 and s["recent_events"]
