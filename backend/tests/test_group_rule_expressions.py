"""Okta Expression Language group rules, and the template / export / import file."""

import pytest

from backend.app.groups import okta_el
from tests.test_group_rules import dept, members, new_group


def expr_body(gid, expression, name="EL rule"):
    return {"name": name, "kind": "expression", "expression": expression, "group_ids": [gid]}


def make_el(admin, gid, expression, activate=True, name="EL rule"):
    r = admin.post("/admin/group-rules", expr_body(gid, expression, name))
    assert r.status_code == 201, r.text
    assert r.json()["kind"] == "expression" and r.json()["expression"] == expression
    if activate:
        assert admin.post(f"/admin/group-rules/{r.json()['id']}/activate").status_code == 200
    return r.json()["id"]


def test_expression_rule_assigns_and_follows_changes(db, admin):
    gid = new_group(admin)
    dept(db, "a@example.com", "Sales")
    dept(db, "b@example.com", "Engineering")
    rid = make_el(admin, gid, 'user.department == "Sales" && user.userType != "Contractor"')
    assert members(admin, gid) == {"a@example.com": rid}
    u = dept(db, "c@example.com", "Engineering")
    admin.patch(f"/admin/users/{u.id}", {"profile_attributes": {"department": "Sales", "user_type": "Employee"}})
    assert "c@example.com" in members(admin, gid)
    admin.patch(f"/admin/users/{u.id}", {"profile_attributes": {"user_type": "Contractor"}})
    assert "c@example.com" not in members(admin, gid)


def test_camel_case_functions_and_ternary(db, admin):
    gid = new_group(admin)
    dept(db, "x@example.com", "Ops")
    u = dept(db, "y@example.com", "Ops")
    u.set_profile_attributes({"department": "Ops", "employee_number": "123"})
    db.commit()
    rid = make_el(admin, gid, 'String.stringContains(user.email, "x@") || (user.employeeNumber != null ? Convert.toInt(user.employeeNumber) > 100 : false)')
    assert set(members(admin, gid)) == {"x@example.com", "y@example.com"}
    assert rid


@pytest.mark.parametrize("expr,why", [
    ('user.firstName == "A"', "edit"),
    ('user.title == "x"', "edit"),
    ('user.nope == "x"', "unknown"),
    ('user.department', "true or false"),
    ('user.department ==', "Expression error"),
    ('System.exit(1)', "Expression error"),
    ('user.department.length() > 0', "Expression error"),
    ('"a" * 3', "Expression error"),
    ('', "Expression error"),
])
def test_bad_expressions_are_refused(admin, expr, why):
    gid = new_group(admin)
    r = admin.post("/admin/group-rules", expr_body(gid, expr))
    assert r.status_code == 422 and why in r.json()["detail"], r.text


def test_runtime_errors_never_grant_membership(db, admin):
    gid = new_group(admin)
    dept(db, "z@example.com", "Sales")
    make_el(admin, gid, 'user.department == "Sales" && user.employeeNumber')  # not boolean at runtime: no match
    assert members(admin, gid) == {}


def test_expression_preview_and_limits(db, admin):
    gid = new_group(admin)
    dept(db, "p@example.com", "Sales")
    r = admin.post("/admin/group-rules/preview", {"kind": "expression", "expression": 'user.department == "Sales"'})
    assert r.status_code == 200 and r.json()["count"] == 1
    long = " || ".join(['user.department == "a"'] * 40)
    assert admin.post("/admin/group-rules", expr_body(gid, long)).status_code == 422
    assert admin.post("/admin/group-rules", expr_body(gid, "(" * 40 + "true" + ")" * 40)).status_code == 422


def test_el_parser_unit():
    ev = lambda e, d=None: okta_el.evaluate(okta_el.parse(e), lambda k: (d or {}).get(k))
    assert ev('1 < 2 and not (2 < 1)') is True
    assert ev("user.a eq 'x'", {"a": "x"}) is True and ev('user.a == "X"', {"a": "x"}) is False
    assert ev('String.stringSwitch("abc", "none", "b", "yes")') == "yes"
    assert ev('Arrays.contains(user.tags, "a")', {"tags": ["a", "b"]}) is True
    assert okta_el.attributes(okta_el.parse('user.login == "a" || user.employeeNumber == "1"')) == {"username", "employee_number"}


def test_template_download_is_importable(admin):
    r = admin.get("/admin/group-rules/template")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    doc = r.json()
    assert doc["format"] == "identityforge.group-rules" and {x["kind"] for x in doc["rules"]} == {"basic", "expression"}
    refused = admin.post("/admin/group-rules/import", {"document": doc})
    assert refused.status_code == 422 and "does not exist" in str(refused.json())
    assert admin.get("/admin/group-rules").json()["items"] == []        # all-or-nothing
    dry = admin.post("/admin/group-rules/import", {"document": doc, "create_missing_groups": True, "dry_run": True})
    assert dry.status_code == 200 and dry.json()["rules"] == 4 and admin.get("/admin/group-rules").json()["items"] == []
    ok = admin.post("/admin/group-rules/import", {"document": doc, "create_missing_groups": True})
    assert ok.status_code == 200 and len(ok.json()["created"]) == 4
    items = admin.get("/admin/group-rules").json()["items"]
    assert {i["status"] for i in items} == {"inactive"} and len(items) == 4       # imported rules never auto-activate
    again = admin.post("/admin/group-rules/import", {"document": doc, "create_missing_groups": True})
    assert again.status_code == 422 and "already exists" in str(again.json())


def test_export_roundtrip_and_import_validation(admin):
    gid = new_group(admin)
    make_el(admin, gid, 'user.department == "Sales"', activate=False)
    exp = admin.get("/admin/group-rules/export").json()
    assert exp["rules"][0] == {"name": "EL rule", "kind": "expression", "groups": ["Sales team"], "expression": 'user.department == "Sales"'}
    base = {"format": "identityforge.group-rules", "version": 1}
    for bad in ({"format": "x", "version": 1, "rules": []}, {**base, "rules": []},
                {**base, "rules": [{"name": "n", "kind": "expression", "expression": "user.firstName == 'a'", "groups": ["Sales team"]}]},
                {**base, "rules": [{"name": "n", "kind": "basic", "conditions": [{"attribute": "title", "operator": "equals", "value": "x"}], "groups": ["Sales team"]}]},
                {**base, "rules": [{"name": "n", "kind": "basic", "conditions": [], "groups": ["Everyone"]}]}):
        assert admin.post("/admin/group-rules/import", {"document": bad}).status_code == 422


def test_only_admins_can_use_template_and_import(member):
    assert member.get("/admin/group-rules/template").status_code == 403
    assert member.post("/admin/group-rules/import", {"document": {}}).status_code == 403


# ---- editor help and live validation (auto-suggest) ---------------------------------------------------------------

def test_every_function_is_documented_for_the_editor():
    cat = okta_el.help_catalog()
    assert {f["name"] for f in cat["functions"]} == set(okta_el.FUNCTIONS)
    for f in cat["functions"]:
        assert f["signature"].startswith(f["name"] + "(") and f["description"] and f["returns"]
        okta_el.parse(f["example"])                       # every documented example is itself valid syntax


def test_expression_help_lists_usable_and_blocked_attributes(admin):
    r = admin.get("/admin/group-rules/expression-help")
    assert r.status_code == 200
    d = r.json()
    names = {a["name"] for a in d["attributes"]}
    assert {"email", "login", "status", "department"} <= names
    blocked = {a["name"] for a in d["blocked_attributes"]}
    assert {"firstName", "lastName"} <= blocked and not (names & blocked)
    assert any(o["token"] == "&&" for o in d["operators"])


def test_validate_expression_endpoint(admin, member):
    ok = admin.post("/admin/group-rules/validate-expression", {"expression": 'user.department == "Sales" && String.len(user.email) > 3'}).json()
    assert ok == {"ok": True, "error": None, "attributes": ["department", "email"]}
    for text, needle in (('user.department ==', "Expression error"), ('String.len(user.email)', "true or false"),
                         ('user.firstName == "x"', "edited by users"), ('user.nope == "x"', "unknown attribute")):
        r = admin.post("/admin/group-rules/validate-expression", {"expression": text}).json()
        assert r["ok"] is False and needle in r["error"], (text, r)
    assert member.post("/admin/group-rules/validate-expression", {"expression": "true"}).status_code == 403
