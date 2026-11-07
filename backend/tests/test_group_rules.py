"""Group rules: attribute-based automatic membership, and the guard rails around it."""

import pytest

from backend.app.config import settings
from tests.conftest import Api, STRONG, make_user


def dept(db, email, department=None, status="active", **kw):
    u = make_user(db, email, **kw)
    if department is not None:
        u.set_profile_attributes({"department": department})
    u.status = status
    db.commit()
    return u


def new_group(admin, name="Sales team"):
    r = admin.post("/admin/groups", {"name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def rule_body(gid, value="Sales", name="Sales rule", **kw):
    return {"name": name, "match": "all", "group_ids": [gid],
            "conditions": [{"attribute": "department", "operator": "equals", "value": value}], **kw}


def members(admin, gid):
    return {m["email"]: m["via_rule"] for m in admin.get(f"/admin/groups/{gid}").json()["members"]}


def make_rule(admin, gid, activate=True, **kw):
    r = admin.post("/admin/group-rules", rule_body(gid, **kw))
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    if activate:
        a = admin.post(f"/admin/group-rules/{rid}/activate")
        assert a.status_code == 200, a.text
    return rid


# ---- access and feature flag -----------------------------------------------------------

def test_admin_only(member, admin):
    gid = new_group(admin)
    assert member.get("/admin/group-rules").status_code == 403
    assert member.post("/admin/group-rules", rule_body(gid)).status_code == 403


def test_feature_flag_turns_the_feature_off(admin, monkeypatch):
    assert admin.get("/admin/features").json() == {"group_rules": True}
    monkeypatch.setattr(settings, "GROUP_RULES_ENABLED", False)
    assert admin.get("/admin/features").json() == {"group_rules": False}
    assert admin.get("/admin/group-rules").status_code == 404


def test_flag_off_means_user_changes_do_not_touch_memberships(db, admin, monkeypatch):
    gid = new_group(admin)
    make_rule(admin, gid)
    monkeypatch.setattr(settings, "GROUP_RULES_ENABLED", False)
    u = admin.post("/admin/users", {"email": "n@example.com", "first_name": "N", "last_name": "N", "password": STRONG,
                                    "profile_attributes": {"department": "Sales"}})
    assert u.status_code == 201
    assert "n@example.com" not in members(admin, gid)


# ---- guard rails: what a rule may look at -----------------------------------------------

@pytest.mark.parametrize("attr", ["title", "primary_phone", "city", "timezone", "locale", "nick_name", "first_name", "last_name"])
def test_rules_cannot_use_attributes_users_can_edit(admin, attr):
    gid = new_group(admin)
    body = rule_body(gid)
    body["conditions"] = [{"attribute": attr, "operator": "equals", "value": "x"}]
    r = admin.post("/admin/group-rules", body)
    assert r.status_code == 422 and "edited by users" in r.json()["detail"]


def test_rule_validation(admin):
    gid = new_group(admin)
    bad = [
        {**rule_body(gid), "conditions": []},
        {**rule_body(gid), "match": "xor"},
        {**rule_body(gid), "conditions": [{"attribute": "department", "operator": "matches_regex", "value": ".*"}]},
        {**rule_body(gid), "conditions": [{"attribute": "department", "operator": "equals", "value": ""}]},
        {**rule_body(gid), "conditions": [{"attribute": "Robert'); DROP", "operator": "equals", "value": "x"}]},
        {**rule_body(gid), "group_ids": [9999]},
        {**rule_body(gid), "group_ids": []},
    ]
    for b in bad:
        assert admin.post("/admin/group-rules", b).status_code == 422, b


def test_system_groups_cannot_be_targets(db, admin):
    from backend.app.groups.model import Group

    g = Group(name="Everyone", is_system_group=True)
    db.add(g)
    db.commit()
    assert admin.post("/admin/group-rules", rule_body(g.id)).status_code == 422


# ---- behaviour ---------------------------------------------------------------------------

def test_new_rule_is_inactive_and_changes_nothing(db, admin):
    gid = new_group(admin)
    dept(db, "s@example.com", "Sales")
    rid = make_rule(admin, gid, activate=False)
    assert admin.get(f"/admin/group-rules/{rid}").json()["status"] == "inactive"
    assert members(admin, gid) == {}


def test_activation_adds_only_matching_active_users(db, admin):
    gid = new_group(admin)
    dept(db, "s1@example.com", "Sales")
    dept(db, "s2@example.com", "sales")             # case-insensitive
    dept(db, "e@example.com", "Engineering")
    dept(db, "none@example.com")
    dept(db, "off@example.com", "Sales", status="deprovisioned")
    rid = make_rule(admin, gid)
    m = members(admin, gid)
    assert set(m) == {"s1@example.com", "s2@example.com"} and set(m.values()) == {rid}
    assert admin.get("/admin/groups").json()["items"][0]["member_count"] == 2


def test_membership_follows_user_changes(db, admin):
    gid = new_group(admin)
    rid = make_rule(admin, gid)
    r = admin.post("/admin/users", {"email": "n@example.com", "first_name": "N", "last_name": "N", "password": STRONG,
                                    "profile_attributes": {"department": "Sales"}})
    uid = r.json()["id"]
    assert members(admin, gid) == {"n@example.com": rid}            # on create
    admin.patch(f"/admin/users/{uid}", {"profile_attributes": {"department": "Support"}})
    assert members(admin, gid) == {}                                # attribute moved out
    admin.patch(f"/admin/users/{uid}", {"profile_attributes": {"department": "Sales"}})
    assert members(admin, gid) == {"n@example.com": rid}
    admin.patch(f"/admin/users/{uid}", {"status": "deprovisioned"})
    assert members(admin, gid) == {}                                # deactivated users drop out
    admin.patch(f"/admin/users/{uid}", {"status": "active"})
    assert members(admin, gid) == {"n@example.com": rid}


def test_any_vs_all(db, admin):
    gid = new_group(admin)
    dept(db, "a@example.com", "Sales")
    dept(db, "b@example.com", "Support")
    body = rule_body(gid)
    body["match"] = "any"
    body["conditions"] = [
        {"attribute": "department", "operator": "equals", "value": "Sales"},
        {"attribute": "department", "operator": "equals", "value": "Support"},
    ]
    rid = admin.post("/admin/group-rules", body).json()["id"]
    admin.post(f"/admin/group-rules/{rid}/activate")
    assert set(members(admin, gid)) == {"a@example.com", "b@example.com"}


@pytest.mark.parametrize("op,value,expected", [
    ("starts_with", "Sal", {"a"}), ("ends_with", "ing", {"c"}), ("contains", "ale", {"a"}),
    ("not_equals", "Sales", {"b", "c", "d"}), ("is_set", "", {"a", "b", "c"}), ("is_not_set", "", {"d"}),
])
def test_operators(db, admin, op, value, expected):
    dept(db, "a@example.com", "Sales")
    dept(db, "b@example.com", "Support")
    dept(db, "c@example.com", "Marketing")
    dept(db, "d@example.com")
    gid = new_group(admin)
    body = rule_body(gid)
    body["conditions"] = [{"attribute": "department", "operator": op, "value": value or "x"}]
    rid = admin.post("/admin/group-rules", body).json()["id"]
    admin.post(f"/admin/group-rules/{rid}/activate")
    got = {e.split("@")[0] for e in members(admin, gid) if e.split("@")[0] in "abcd" and len(e.split("@")[0]) == 1}
    assert got == expected


def test_email_domain_rule(db, admin):
    gid = new_group(admin, "Contractors")
    make_user(db, "c1@contractor.example")
    make_user(db, "e1@corp.example")
    body = rule_body(gid, name="Contractors")
    body["conditions"] = [{"attribute": "email", "operator": "ends_with", "value": "@contractor.example"}]
    rid = admin.post("/admin/group-rules", body).json()["id"]
    admin.post(f"/admin/group-rules/{rid}/activate")
    assert set(members(admin, gid)) == {"c1@contractor.example"}


# ---- manual vs rule-managed ---------------------------------------------------------------

def test_manual_membership_is_never_taken_over_or_removed_by_rules(db, admin):
    gid = new_group(admin)
    u = dept(db, "s@example.com", "Sales")
    assert admin.post(f"/admin/groups/{gid}/members", {"user_id": u.id}).status_code == 201
    rid = make_rule(admin, gid)
    assert members(admin, gid) == {"s@example.com": None}          # still manual
    admin.patch(f"/admin/users/{u.id}", {"profile_attributes": {"department": "Other"}})
    assert members(admin, gid) == {"s@example.com": None}          # rule does not remove it
    admin.post(f"/admin/group-rules/{rid}/deactivate")
    assert members(admin, gid) == {"s@example.com": None}


def test_rule_managed_membership_cannot_be_removed_by_hand(db, admin):
    gid = new_group(admin)
    u = dept(db, "s@example.com", "Sales")
    make_rule(admin, gid)
    r = admin.delete(f"/admin/groups/{gid}/members/{u.id}")
    assert r.status_code == 409 and "group rule" in r.json()["detail"]
    assert "s@example.com" in members(admin, gid)


def test_deactivate_and_delete_remove_only_rule_memberships(db, admin):
    gid = new_group(admin)
    manual = dept(db, "m@example.com", "Other")
    dept(db, "s@example.com", "Sales")
    admin.post(f"/admin/groups/{gid}/members", {"user_id": manual.id})
    rid = make_rule(admin, gid)
    assert set(members(admin, gid)) == {"m@example.com", "s@example.com"}
    assert admin.post(f"/admin/group-rules/{rid}/deactivate").json()["removed"] == 1
    assert set(members(admin, gid)) == {"m@example.com"}
    admin.post(f"/admin/group-rules/{rid}/activate")
    assert set(members(admin, gid)) == {"m@example.com", "s@example.com"}
    assert admin.delete(f"/admin/group-rules/{rid}").json()["removed"] == 1
    assert set(members(admin, gid)) == {"m@example.com"}
    assert admin.get("/admin/groups").json()["items"][0]["member_count"] == 1


def test_active_rules_must_be_deactivated_before_editing(db, admin):
    gid = new_group(admin)
    rid = make_rule(admin, gid)
    assert admin.put(f"/admin/group-rules/{rid}", rule_body(gid, value="Support")).status_code == 409
    admin.post(f"/admin/group-rules/{rid}/deactivate")
    r = admin.put(f"/admin/group-rules/{rid}", rule_body(gid, value="Support"))
    assert r.status_code == 200 and r.json()["conditions"][0]["value"] == "Support"


def test_duplicate_rule_name_rejected(admin):
    gid = new_group(admin)
    make_rule(admin, gid, activate=False)
    assert admin.post("/admin/group-rules", rule_body(gid)).status_code == 409


def test_preview_counts_without_changing_anything(db, admin):
    gid = new_group(admin)
    dept(db, "s@example.com", "Sales")
    dept(db, "e@example.com", "Eng")
    r = admin.post("/admin/group-rules/preview", {"match": "all", "conditions": rule_body(gid)["conditions"]})
    assert r.json()["count"] == 1 and r.json()["sample"][0]["email"] == "s@example.com"
    assert members(admin, gid) == {}


def test_users_cannot_edit_their_way_into_a_group(db, admin, member):
    """The attacker path: a rule on an attribute the user controls. Both halves are closed."""
    gid = new_group(admin)
    make_rule(admin, gid)
    assert member.patch("/me/profile", {"profile_attributes": {"department": "Sales"}}).status_code == 403
    assert "member@example.com" not in members(admin, gid)


def test_audit_trail(db, admin):
    gid = new_group(admin)
    dept(db, "s@example.com", "Sales")
    rid = make_rule(admin, gid)
    admin.post(f"/admin/group-rules/{rid}/deactivate")
    for action in ("GROUP_RULE_CREATED", "GROUP_RULE_ACTIVATED", "GROUP_RULE_DEACTIVATED"):
        assert admin.get(f"/admin/audit?action={action}").json()["total"] == 1
    added = admin.get("/admin/audit?action=GROUP_MEMBER_ADDED").json()["items"][0]["metadata"]
    assert added["via_rule"] == rid


# ---- create user: groups and generated password -------------------------------------------

def test_create_user_with_groups_and_generated_password(db, admin):
    gid = new_group(admin)
    r = admin.post("/admin/users", {"email": "new@example.com", "first_name": "N", "last_name": "U",
                                    "generate_password": True, "group_ids": [gid]})
    assert r.status_code == 201, r.text
    pw = r.json()["temporary_password"]
    assert len(pw) >= 16 and Api().login("new@example.com", pw).status_code == 200
    assert "new@example.com" in members(admin, gid)
    assert "temporary_password" not in admin.get(f"/admin/users/{r.json()['id']}").text


def test_create_user_password_xor_generate(admin):
    base = {"email": "x@example.com", "first_name": "N", "last_name": "U"}
    assert admin.post("/admin/users", {**base}).status_code == 422
    assert admin.post("/admin/users", {**base, "password": STRONG, "generate_password": True}).status_code == 422
    assert admin.post("/admin/users", {**base, "password": STRONG, "group_ids": [999]}).status_code == 422
