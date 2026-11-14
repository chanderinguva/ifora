"""User-list role display follows real assignments, never infers org admin from a flag."""
from backend.app.admin_roles.models import GroupAdminRole
from backend.app.groups.model import Group
from tests.conftest import make_user


def test_direct_role_label_matches_filtered_user_list(admin):
    response = admin.get("/admin/users?role=org_admin").json()
    row = next(u for u in response["Resources"] if u["id"] == admin.user.id)
    assert row["admin_roles"] == [
        {"id": "org_admin", "label": "Organization administrator", "sources": ["direct"]}
    ]


def test_group_and_direct_role_sources_are_deduplicated(admin, db):
    user = make_user(db, "role-label@example.com", admin=True, roles=("app_admin",))
    group = Group(name="Role label group", group_type="team")
    db.add(group)
    db.flush()
    db.add(GroupAdminRole(group_id=group.id, role="app_admin", granted_by=admin.user.id))
    db.add(GroupAdminRole(group_id=group.id, role="report_admin", granted_by=admin.user.id))
    group.members.append(user)
    db.commit()
    response = admin.get("/admin/users?role=app_admin").json()
    row = next(u for u in response["Resources"] if u["id"] == user.id)
    assert row["admin_roles"] == [
        {"id": "app_admin", "label": "Application administrator", "sources": ["direct", "group"]},
        {"id": "report_admin", "label": "Report administrator", "sources": ["group"]},
    ]


def test_no_roles_does_not_invent_org_admin(admin, db):
    user = make_user(db, "no-role-label@example.com", admin=True, roles=None)
    row = next(u for u in admin.get("/admin/users?q=no-role-label").json()["Resources"] if u["id"] == user.id)
    assert row["admin_roles"] == []
