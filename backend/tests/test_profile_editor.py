"""Profile editor: the attribute catalog drives admin edits, self-service and group rules."""

from tests.conftest import make_user


def create(admin, **kw):
    body = {"key": "grade", "display_name": "Grade", "data_type": "string", **kw}
    return admin.post("/admin/profile-attributes", body)


def keys(admin):
    return {a["key"]: a for a in admin.get("/admin/profile-attributes").json()["items"]}


def test_defaults_are_seeded_and_admin_only(admin, member):
    k = keys(admin)
    assert {"title", "phone", "location", "bio", "timezone", "locale", "department", "employee_id", "manager", "cost_center"} <= set(k)
    assert k["department"]["user_editable"] is False and k["title"]["user_editable"] is True
    assert member.get("/admin/profile-attributes").status_code == 403
    assert member.post("/admin/profile-attributes", {"key": "x", "display_name": "X"}).status_code == 403


def test_create_validates_key_type_and_reserved(admin):
    assert create(admin, key="Bad Key").status_code == 422
    assert create(admin, key="email").status_code == 422
    assert create(admin, data_type="timezone").status_code == 422
    assert create(admin, data_type="enum").status_code == 422  # needs options
    assert create(admin, data_type="enum", enum_options=["a", "a"]).status_code == 422
    assert create(admin, key="department").status_code == 409
    r = create(admin, data_type="enum", enum_options=["L1", "L2"])
    assert r.status_code == 201 and r.json()["enum_options"] == ["L1", "L2"]


def test_admin_sets_typed_values_on_users(db, admin):
    create(admin, key="level", display_name="Level", data_type="number")
    create(admin, key="remote", display_name="Remote", data_type="boolean")
    create(admin, key="band", display_name="Band", data_type="enum", enum_options=["A", "B"])
    u = make_user(db, "t@example.com")
    ok = admin.patch(f"/admin/users/{u.id}", {"profile_attributes": {"department": "Sales", "level": 3, "remote": True, "band": "A"}})
    assert ok.status_code == 200, ok.text
    assert admin.patch(f"/admin/users/{u.id}", {"profile_attributes": {"level": "high"}}).status_code == 422
    assert admin.patch(f"/admin/users/{u.id}", {"profile_attributes": {"band": "Z"}}).status_code == 422
    assert admin.patch(f"/admin/users/{u.id}", {"profile_attributes": {"nope": "x"}}).status_code == 422


def test_users_edit_only_user_editable_attributes(db, admin):
    u = make_user(db, "e@example.com")
    s = __import__("tests.conftest", fromlist=["Api"]).Api()
    assert s.login("e@example.com").status_code == 200
    assert s.patch("/me/profile", {"profile_attributes": {"title": "Eng"}}).status_code == 200
    assert s.patch("/me/profile", {"profile_attributes": {"department": "Exec"}}).status_code == 403
    # flipping department to user-editable is allowed (no rules use it) and takes effect
    assert admin.patch("/admin/profile-attributes/department", {"user_editable": True}).status_code == 200
    assert s.patch("/me/profile", {"profile_attributes": {"department": "Exec"}}).status_code == 200


def test_rule_attributes_must_be_admin_managed_catalog_attributes(admin):
    g = admin.post("/admin/groups", {"name": "G"}).json()["id"]

    def rule(attr):
        return admin.post("/admin/group-rules", {"name": "r", "match": "all", "group_ids": [g],
                                                 "conditions": [{"attribute": attr, "operator": "equals", "value": "x"}]})

    assert rule("department").status_code == 201
    assert rule("title").status_code == 422      # user-editable
    assert rule("unknown_attr").status_code == 422


def test_cannot_make_rule_attribute_user_editable_or_delete_it(admin):
    g = admin.post("/admin/groups", {"name": "G"}).json()["id"]
    admin.post("/admin/group-rules", {"name": "r", "match": "all", "group_ids": [g],
                                      "conditions": [{"attribute": "department", "operator": "equals", "value": "Sales"}]})
    assert admin.patch("/admin/profile-attributes/department", {"user_editable": True}).status_code == 409
    create(admin, key="team", display_name="Team")
    admin.post("/admin/group-rules", {"name": "r2", "match": "all", "group_ids": [g],
                                      "conditions": [{"attribute": "team", "operator": "equals", "value": "x"}]})
    assert admin.delete("/admin/profile-attributes/team").status_code == 409


def test_built_ins_cannot_be_deleted_custom_delete_clears_values(db, admin):
    assert admin.delete("/admin/profile-attributes/title").status_code == 403
    create(admin, key="badge", display_name="Badge")
    u = make_user(db, "b@example.com")
    assert admin.patch(f"/admin/users/{u.id}", {"profile_attributes": {"badge": "7"}}).status_code == 200
    r = admin.delete("/admin/profile-attributes/badge")
    assert r.status_code == 200 and r.json()["users_cleared"] == 1
    db.expire_all()
    assert "badge" not in db.get(type(u), u.id).get_profile_attributes()
    assert admin.delete("/admin/profile-attributes/badge").status_code == 404
