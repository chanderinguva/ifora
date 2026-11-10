"""Group CRUD and membership."""

from tests.conftest import make_user


def test_group_crud(admin):
    r = admin.post("/admin/groups", {"name": "Engineering", "description": "Builders"})
    assert r.status_code == 201
    gid = r.json()["id"]
    assert admin.post("/admin/groups", {"name": "engineering"}).status_code == 409
    assert admin.patch(f"/admin/groups/{gid}", {"description": "Makers"}).json()["description"] == "Makers"
    assert admin.get("/admin/groups?q=engi").json()["totalResults"] == 1
    assert admin.delete(f"/admin/groups/{gid}").status_code == 200
    assert admin.get(f"/admin/groups/{gid}").status_code == 404


def test_membership_and_counts(admin, db):
    u = make_user(db, "m@example.com")
    gid = admin.post("/admin/groups", {"name": "Ops"}).json()["id"]
    r = admin.post(f"/admin/groups/{gid}/members", {"user_id": u.id})
    assert r.status_code == 201 and r.json()["member_count"] == 1
    assert admin.post(f"/admin/groups/{gid}/members", {"user_id": u.id}).status_code == 409
    assert admin.post(f"/admin/groups/{gid}/members", {"user_id": 9999}).status_code == 404
    assert admin.get(f"/admin/users/{u.id}").json()["groups"][0]["name"] == "Ops"
    r = admin.delete(f"/admin/groups/{gid}/members/{u.id}")
    assert r.status_code == 200 and r.json()["member_count"] == 0
    assert admin.delete(f"/admin/groups/{gid}/members/{u.id}").status_code == 404


def test_deleting_user_removes_membership_even_if_they_added_others(admin, db):
    u = make_user(db, "m@example.com")
    gid = admin.post("/admin/groups", {"name": "Ops"}).json()["id"]
    admin.post(f"/admin/groups/{gid}/members", {"user_id": u.id})
    assert admin.delete(f"/admin/users/{u.id}").status_code == 200
    assert admin.get(f"/admin/groups/{gid}").json()["members"] == []


def test_deleting_adder_keeps_other_members(super_admin, db):
    helper = make_user(db, "helper@example.com", admin=True)
    from tests.conftest import Api

    a = Api()
    a.login(helper.email)
    u = make_user(db, "m@example.com")
    gid = a.post("/admin/groups", {"name": "Ops"}).json()["id"]
    a.post(f"/admin/groups/{gid}/members", {"user_id": u.id})
    assert super_admin.delete(f"/admin/users/{helper.id}").status_code == 200
    assert len(super_admin.get(f"/admin/groups/{gid}").json()["members"]) == 1


def test_group_validation(admin):
    assert admin.post("/admin/groups", {"name": ""}).status_code == 422
    assert admin.post("/admin/groups", {"name": "   "}).status_code == 422
    assert admin.post("/admin/groups", {"name": "x" * 101}).status_code == 422
