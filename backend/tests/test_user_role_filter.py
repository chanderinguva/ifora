"""The Role filter of GET /admin/users: account kind, or an administrator role held directly or through a group."""

from tests.conftest import make_user


def test_user_list_filters_by_role(db, super_admin):
    plain = make_user(db, "filter.plain@example.com")
    helper = make_user(db, "filter.helper@example.com", admin=True, roles=None)
    grouped = make_user(db, "filter.grouped@example.com", admin=True, roles=None)
    assert super_admin.put(f"/admin/roles/users/{helper.id}", {"roles": ["help_desk_admin"]}).status_code == 200
    g = super_admin.post("/admin/groups", {"name": "Team - Filter", "type": "team", "owner_user_id": super_admin.user.id}).json()
    assert super_admin.put(f"/admin/roles/groups/{g['id']}", {"roles": ["help_desk_admin"]}).status_code == 200
    assert super_admin.post(f"/admin/groups/{g['id']}/members", {"user_id": grouped.id}).status_code == 201

    def emails(role):
        r = super_admin.get(f"/admin/users?role={role}&count=100")
        assert r.status_code == 200, r.text
        return {u["email"] for u in r.json()["Resources"]}

    both = {"filter.helper@example.com", "filter.grouped@example.com"}
    assert both <= emails("help_desk_admin")
    assert "filter.plain@example.com" not in emails("help_desk_admin")
    assert emails("report_admin").isdisjoint(both)
    assert "filter.plain@example.com" in emails("user") and "filter.helper@example.com" not in emails("user")
    assert "filter.helper@example.com" in emails("admin")
    assert super_admin.user.email in emails("super_admin") and "filter.helper@example.com" not in emails("super_admin")
    assert super_admin.get("/admin/users?role=nope").status_code == 422
    assert plain.email == "filter.plain@example.com"
