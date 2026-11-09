"""Administrator roles carried by groups, and group types / metadata (ADR 019)."""

from datetime import date, timedelta

from tests.conftest import Api, make_user


def team(super_admin, name="Team - Support", **kw):
    r = super_admin.post("/admin/groups", {"name": name, "type": "team", "owner_user_id": super_admin.user.id, **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def join(super_admin, gid, user):
    assert super_admin.post(f"/admin/groups/{gid}/members", {"user_id": user.id}).status_code == 201


def login(db, email="helper@example.com", **kw):
    u = make_user(db, email, admin=True, roles=None, **kw)
    a = Api()
    assert a.login(u.email).status_code == 200
    a.user = u
    return a, u


# ---- roles via groups -----------------------------------------------------------------------------------

def test_group_membership_grants_the_group_roles(db, super_admin):
    gid = team(super_admin)
    a, u = login(db)
    assert a.get("/admin/users").status_code == 403
    assert super_admin.put(f"/admin/roles/groups/{gid}", {"roles": ["help_desk_admin"]}).status_code == 200
    join(super_admin, gid, u)
    assert a.get("/admin/users").status_code == 200                      # via the group, immediately
    assert a.post("/admin/groups", {"name": "x"}).status_code == 403     # help desk cannot create groups
    acc = a.get("/me/admin-access").json()
    assert acc["roles"] == ["help_desk_admin"] and acc["sources"]["help_desk_admin"][0]["via"] == "group"


def test_leaving_the_group_removes_the_roles(db, super_admin):
    gid = team(super_admin)
    super_admin.put(f"/admin/roles/groups/{gid}", {"roles": ["read_only_admin"]})
    a, u = login(db)
    join(super_admin, gid, u)
    assert a.get("/admin/users").status_code == 200
    assert super_admin.delete(f"/admin/groups/{gid}/members/{u.id}").status_code == 200
    assert a.get("/admin/users").status_code == 403                       # no fall back to full access


def test_direct_and_group_roles_combine_and_show_their_source(db, super_admin):
    gid = team(super_admin)
    super_admin.put(f"/admin/roles/groups/{gid}", {"roles": ["report_admin"]})
    a, u = login(db)
    join(super_admin, gid, u)
    super_admin.put(f"/admin/roles/users/{u.id}", {"roles": ["help_desk_admin"]})
    got = super_admin.get(f"/admin/roles/users/{u.id}").json()
    assert got["roles"] == ["help_desk_admin"] and got["effective_roles"] == ["help_desk_admin", "report_admin"]
    assert a.get("/admin/audit").status_code == 200 and a.get("/admin/users").status_code == 200


def test_only_super_admins_manage_group_roles(db, super_admin, admin):
    gid = team(super_admin)
    assert admin.get(f"/admin/roles/groups/{gid}").status_code == 403
    assert admin.put(f"/admin/roles/groups/{gid}", {"roles": ["read_only_admin"]}).status_code == 403


def test_only_team_groups_can_carry_roles(super_admin):
    r = super_admin.post("/admin/groups", {"name": "Project - X", "type": "project", "owner_user_id": super_admin.user.id,
                                           "review_by": str(date.today() + timedelta(days=30))})
    assert super_admin.put(f"/admin/roles/groups/{r.json()['id']}", {"roles": ["read_only_admin"]}).status_code == 409
    gid = team(super_admin)
    assert super_admin.put(f"/admin/roles/groups/{gid}", {"roles": ["nope"]}).status_code == 400
    assert super_admin.put(f"/admin/roles/groups/{gid}", {"roles": ["read_only_admin"]}).status_code == 200
    assert super_admin.patch(f"/admin/groups/{gid}", {"type": "project", "review_by": str(date.today())}).status_code == 409


def test_role_group_membership_is_super_admin_only(db, super_admin, admin):
    gid = team(super_admin)
    super_admin.put(f"/admin/roles/groups/{gid}", {"roles": ["org_admin"]})
    u = make_user(db, "target@example.com")
    assert admin.post(f"/admin/groups/{gid}/members", {"user_id": u.id}).status_code == 403
    join(super_admin, gid, u)
    assert admin.delete(f"/admin/groups/{gid}/members/{u.id}").status_code == 403
    assert admin.delete(f"/admin/groups/{gid}").status_code == 403
    r = admin.post("/admin/users", {"email": "n@example.com", "first_name": "N", "last_name": "U", "generate_password": True, "group_ids": [gid]})
    assert r.status_code == 403


def test_rules_cannot_target_role_groups_unless_super_admin(db, super_admin, admin):
    gid = team(super_admin)
    super_admin.put(f"/admin/roles/groups/{gid}", {"roles": ["read_only_admin"]})
    body = {"name": "Rule", "match": "all", "kind": "basic", "group_ids": [gid], "conditions": [{"attribute": "email", "operator": "contains", "value": "@"}]}
    assert admin.post("/admin/group-rules", body).status_code == 403
    assert super_admin.post("/admin/group-rules", body).status_code == 201


def test_recipes_cannot_change_role_group_membership(db, super_admin, admin):
    from tests.recipe_helpers import definition, jobs, make_recipe, new_user, run_worker, step, steps_of

    gid = team(super_admin)
    super_admin.put(f"/admin/roles/groups/{gid}", {"roles": ["read_only_admin"]})
    rid = make_recipe(admin, definition("user.created", [step("s1", "add_to_group", {"group_id": gid})]))
    u = new_user(admin)
    run_worker()
    (j,) = jobs(db, rid)
    assert j.status == "failed"
    assert "administrator roles" in (steps_of(db, j.id)[0].error or "")
    assert super_admin.get(f"/admin/groups/{gid}").json()["member_count"] == 0 and u["id"]


def test_scim_cannot_change_role_group_membership(db, super_admin):
    from backend.app.groups.model import Group
    from tests.test_scim import PATCH, Scim, mk_token

    gid = team(super_admin)
    super_admin.put(f"/admin/roles/groups/{gid}", {"roles": ["read_only_admin"]})
    u = make_user(db, "scim.target@example.com")
    scim = Scim(mk_token(db))
    r = scim.patch(f"/Groups/{db.get(Group, gid).public_id}", [{"op": "add", "path": "members", "value": [{"value": u.public_id}]}])
    assert r.status_code == 403 and "administrator roles" in r.text
    assert super_admin.get(f"/admin/groups/{gid}").json()["member_count"] == 0 and PATCH


# ---- group types and metadata ---------------------------------------------------------------------------

def test_standards_document_lists_the_types(admin):
    d = admin.get("/admin/groups/standards").json()
    assert [t["id"] for t in d["types"]] == ["team", "project", "app_access", "push", "app", "other"]
    assert d["sensitivity"] == ["low", "medium", "high"]


def test_metadata_round_trip_and_required_fields(super_admin, db):
    owner = make_user(db, "owner@example.com")
    r = super_admin.post("/admin/groups", {"name": "App - CRM - Admin", "type": "app_access", "owner_user_id": owner.id, "sensitivity": "high",
                                           "tags": ["Crm", "tier-1"], "attributes": {"cost_center": "CC-9"}})
    assert r.status_code == 201, r.text
    g = r.json()
    assert (g["type"], g["owner_user_id"], g["sensitivity"], g["tags"], g["attributes"]) == ("app_access", owner.id, "high", ["crm", "tier-1"], {"cost_center": "CC-9"})
    assert super_admin.post("/admin/groups", {"name": "No owner", "type": "team"}).status_code == 422
    assert super_admin.post("/admin/groups", {"name": "P", "type": "project", "owner_user_id": owner.id}).status_code == 422   # needs review_by
    assert super_admin.post("/admin/groups", {"name": "Odd", "type": "mystery"}).status_code == 422
    assert super_admin.post("/admin/groups", {"name": "Bad", "sensitivity": "extreme"}).status_code == 422
    assert super_admin.post("/admin/groups", {"name": "Bad2", "tags": ["Bad Tag!"]}).status_code == 422
    assert super_admin.post("/admin/groups", {"name": "Bad3", "attributes": {"Bad Key": "x"}}).status_code == 422
    assert super_admin.post("/admin/groups", {"name": "Bad4", "owner_user_id": 999999}).status_code == 422
    assert super_admin.post("/admin/groups", {"name": "Plain"}).json()["type"] == "other"


def test_update_metadata_and_audit(super_admin, db):
    gid = team(super_admin)
    r = super_admin.patch(f"/admin/groups/{gid}", {"sensitivity": "medium", "tags": ["a"], "attributes": {"k": "v"}})
    assert r.status_code == 200 and r.json()["sensitivity"] == "medium" and r.json()["tags"] == ["a"]
    assert super_admin.patch(f"/admin/groups/{gid}", {"owner_user_id": None}).status_code == 422   # a team needs an owner
    ev = super_admin.get("/admin/audit?action=GROUP_UPDATED").json()["items"]
    assert ev and "sensitivity" in ev[0]["metadata"]["changed"]


def test_list_filters_and_analytics(super_admin, db):
    owner = make_user(db, "o2@example.com")
    team(super_admin, "Team - A")
    super_admin.post("/admin/groups", {"name": "Legacy"})
    super_admin.post("/admin/groups", {"name": "App - X - User", "type": "app_access", "owner_user_id": owner.id, "sensitivity": "high",
                                       "tags": ["finance"]})
    super_admin.post("/admin/groups", {"name": "Project - Old", "type": "project", "owner_user_id": owner.id,
                                       "review_by": str(date.today() - timedelta(days=1))})
    names = lambda q: sorted(g["name"] for g in super_admin.get(f"/admin/groups{q}").json()["items"])  # noqa: E731
    assert names("?type=app_access") == ["App - X - User"]
    assert names("?tag=finance") == ["App - X - User"]
    assert names("?sensitivity=high") == ["App - X - User"]
    assert "Legacy" in names("?ownerless=true")
    a = super_admin.get("/admin/groups/analytics").json()
    assert a["by_type"]["team"] == 1 and a["by_type"]["other"] == 1 and a["unclassified"] == 1
    assert a["review_overdue_count"] == 1 and a["review_overdue"][0]["name"] == "Project - Old"
    assert a["empty"] == 4 and a["without_owner_count"] == 0
    assert a["by_sensitivity"]["high"] == 1


def test_group_analytics_follow_the_groups_area(db, super_admin):
    a, _ = login(db, "nogroups@example.com")
    assert a.get("/admin/groups/analytics").status_code == 403
