"""Lookup tables: admin API, CSV, the lookup and write steps, and the trust (taint) rules (ADR 021 s.2)."""

import pytest

from backend.app.audit.model import AuditEvent
from backend.app.recipes import lookup
from backend.app.recipes.models import LookupRow, LookupTable
from tests.recipe_helpers import definition, jobs, make_recipe, rkey, run_worker, step, steps_of  # noqa: F401

LOG = lambda sid, msg: step(sid, "log", {"message": msg})  # noqa: E731
COLS = [{"name": "code", "type": "text"}, {"name": "limit", "type": "number"}, {"name": "active", "type": "boolean"}, {"name": "since", "type": "date"}]


def mk(admin, name="depts", key="code", managed=True, cols=COLS):
    r = admin.post("/admin/lookup-tables", {"name": name, "columns": cols, "key_column": key, "admin_managed": managed})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def add(admin, tid, **values):
    r = admin.post(f"/admin/lookup-tables/{tid}/rows", {"values": values})
    assert r.status_code == 201, r.text
    return r.json()


_n = [0]


def save(admin, steps):
    _n[0] += 1
    return admin.post("/admin/recipes", {"name": f"R{_n[0]}", "definition": definition("manual", steps)})


def run(admin, db, steps, name="R"):
    rid = make_recipe(admin, definition("manual", steps), name=name)
    admin.post(f"/admin/recipes/{rid}/run", {})
    run_worker()
    (j,) = jobs(db, rid)
    return j, {s.step_id: s for s in steps_of(db, j.id)}


# ---- tables ----------------------------------------------------------------------------------------------------------

def test_create_list_update_and_delete_a_table(admin):
    tid = mk(admin)
    t = admin.get(f"/admin/lookup-tables/{tid}").json()
    assert t["name"] == "depts" and t["key_column"] == "code" and t["admin_managed"] is True and t["row_count"] == 0
    assert [x["name"] for x in admin.get("/admin/lookup-tables").json()["items"]] == ["depts"]
    r = admin.put(f"/admin/lookup-tables/{tid}", {"description": "Departments", "add_columns": [{"name": "owner", "type": "text"}]})
    assert r.status_code == 200 and r.json()["description"] == "Departments" and r.json()["columns"][-1]["name"] == "owner"
    assert admin.delete(f"/admin/lookup-tables/{tid}").status_code == 200
    assert admin.get(f"/admin/lookup-tables/{tid}").status_code == 404


@pytest.mark.parametrize("body", [
    {"name": "Bad Name", "columns": COLS}, {"name": "x", "columns": []}, {"name": "x", "columns": [{"name": "a", "type": "money"}]},
    {"name": "x", "columns": [{"name": "A", "type": "text"}]}, {"name": "x", "columns": [{"name": "a", "type": "text"}, {"name": "a", "type": "text"}]},
    {"name": "x", "columns": [{"name": "a", "type": "text"}], "key_column": "b"},
    {"name": "x", "columns": [{"name": f"c{i}", "type": "text"} for i in range(21)]},
])
def test_table_definitions_are_validated(admin, body):
    assert admin.post("/admin/lookup-tables", body).status_code == 422


def test_names_are_unique_and_tables_are_limited(admin, monkeypatch):
    mk(admin)
    assert admin.post("/admin/lookup-tables", {"name": "depts", "columns": COLS}).status_code == 409
    monkeypatch.setattr(lookup, "MAX_TABLES", 1)
    assert admin.post("/admin/lookup-tables", {"name": "other", "columns": COLS}).status_code == 422


def test_only_administrators_with_the_automation_area_can_use_it(admin, member):
    tid = mk(admin)
    assert member.get("/admin/lookup-tables").status_code == 403
    assert member.post(f"/admin/lookup-tables/{tid}/rows", {"values": {"code": "x"}}).status_code == 403


def test_a_table_used_by_a_recipe_cannot_be_deleted(admin, rkey):
    tid = mk(admin)
    make_recipe(admin, definition("manual", [step("a", "lookup_row", {"table": "depts", "column": "code", "value": "x"})]), name="Uses it")
    r = admin.delete(f"/admin/lookup-tables/{tid}")
    assert r.status_code == 409 and "Uses it" in r.json()["detail"]
    assert admin.get(f"/admin/lookup-tables/{tid}").json()["used_by"] == ["Uses it"]


# ---- rows ------------------------------------------------------------------------------------------------------------

def test_rows_are_typed_and_keys_are_unique(admin, db):
    tid = mk(admin)
    r = add(admin, tid, code="ENG", limit="12.0", active="yes", since="2030-01-31")
    assert r["values"] == {"code": "ENG", "limit": 12, "active": True, "since": "2030-01-31"}
    assert admin.post(f"/admin/lookup-tables/{tid}/rows", {"values": {"code": "ENG"}}).status_code == 422          # duplicate key
    for bad in ({"code": "A", "limit": "abc"}, {"code": "A", "active": "maybe"}, {"code": "A", "since": "31/01/2030"},
                {"code": "A", "nope": "x"}, {"code": ""}, {"limit": 3}, {"code": "x" * 501}):
        assert admin.post(f"/admin/lookup-tables/{tid}/rows", {"values": bad}).status_code == 422, bad
    assert admin.get(f"/admin/lookup-tables/{tid}").json()["row_count"] == 1
    r2 = admin.put(f"/admin/lookup-tables/{tid}/rows/{r['id']}", {"values": {"code": "ENG2", "limit": 5}})
    assert r2.status_code == 200 and r2.json()["values"]["code"] == "ENG2" and r2.json()["values"]["active"] is None
    assert admin.delete(f"/admin/lookup-tables/{tid}/rows/{r['id']}").status_code == 200
    assert admin.get(f"/admin/lookup-tables/{tid}").json()["row_count"] == 0


def test_search_paging_and_the_row_limit(admin, monkeypatch):
    tid = mk(admin)
    for c in ("ALPHA", "BETA", "GAMMA_1"):
        add(admin, tid, code=c)
    assert [r["values"]["code"] for r in admin.get(f"/admin/lookup-tables/{tid}/rows?q=et").json()["Resources"]] == ["BETA"]
    assert admin.get(f"/admin/lookup-tables/{tid}/rows?q=%25").json()["totalResults"] == 0              # a wildcard is not a wildcard
    assert len(admin.get(f"/admin/lookup-tables/{tid}/rows?count=2").json()["Resources"]) == 2
    monkeypatch.setattr(lookup, "MAX_ROWS", 3)
    assert admin.post(f"/admin/lookup-tables/{tid}/rows", {"values": {"code": "DELTA"}}).status_code == 422


def test_row_changes_are_audited(admin, db):
    tid = mk(admin)
    add(admin, tid, code="ENG")
    db.expire_all()
    actions = [e.action for e in db.query(AuditEvent).order_by(AuditEvent.id)]
    assert "LOOKUP_TABLE_CREATED" in actions and "LOOKUP_ROWS_CHANGED" in actions


# ---- CSV -------------------------------------------------------------------------------------------------------------

def test_csv_import_is_all_or_nothing_and_export_neutralises_formulas(admin, db):
    tid = mk(admin)
    good = "code,limit,active,since\nENG,10,true,2030-01-01\nOPS,20,false,\n"
    r = admin.post(f"/admin/lookup-tables/{tid}/import", {"csv": good})
    assert r.status_code == 200 and r.json()["imported"] == 2
    bad = "code,limit,active,since\nNEW,1,true,\nENG,2,true,\nBAD,x,true,\n"
    r = admin.post(f"/admin/lookup-tables/{tid}/import", {"csv": bad})
    assert r.status_code == 422 and "line 3" in r.json()["detail"] and "line 4" in r.json()["detail"]
    assert admin.get(f"/admin/lookup-tables/{tid}").json()["row_count"] == 2                       # nothing was written
    assert admin.post(f"/admin/lookup-tables/{tid}/import", {"csv": "code,limit\nx,1\n"}).status_code == 422    # wrong header
    r = admin.post(f"/admin/lookup-tables/{tid}/import", {"csv": "code,limit,active,since\n=CMD(),1,true,\n", "mode": "replace"})
    assert r.status_code == 200 and admin.get(f"/admin/lookup-tables/{tid}").json()["row_count"] == 1
    out = admin.get(f"/admin/lookup-tables/{tid}/export")
    assert out.status_code == 200 and "'=CMD()" in out.text and out.text.splitlines()[0] == "code,limit,active,since"
    assert "LOOKUP_ROWS_EXPORTED" in [e.action for e in db.query(AuditEvent)]


def test_csv_import_row_limits(admin, monkeypatch):
    tid = mk(admin)
    monkeypatch.setattr(lookup, "MAX_IMPORT_ROWS", 2)
    assert admin.post(f"/admin/lookup-tables/{tid}/import", {"csv": "code,limit,active,since\na,,,\nb,,,\nc,,,\n"}).status_code == 422


# ---- the lookup step ---------------------------------------------------------------------------------------------------

def test_lookup_row_reads_a_row_and_can_drive_a_decision(db, admin, rkey):
    tid = mk(admin)
    add(admin, tid, code="ENG", limit=10, active=True)
    j, out = run(admin, db, [
        step("a", "lookup_row", {"table": "depts", "column": "code", "value": "ENG"}),
        step("b", "lookup_row", {"table": "depts", "column": "code", "value": "NOPE"}),
        step("c", "condition", {"match": "all", "conditions": [{"left": "steps.a.output.found", "operator": "equals", "value": "true"}]},
             then=[LOG("yes", "limit={{steps.a.output.row.limit}} found_b={{steps.b.output.found}}")], **{"else": [LOG("no", "x")]}),
    ])
    assert j.status == "succeeded", j.error
    assert out["a"].output["row"]["limit"] == 10 and out["a"].output["count"] == 1
    assert out["b"].output == {"found": False, "count": 0, "row": {}}
    assert out["yes"].output["message"] == "limit=10 found_b=false" and "no" not in out


def test_lookup_by_a_non_key_column_and_typed_values(db, admin, rkey):
    tid = mk(admin)
    add(admin, tid, code="A", limit=5, active=True)
    add(admin, tid, code="B", limit=5, active=False)
    j, out = run(admin, db, [step("a", "lookup_row", {"table": "depts", "column": "limit", "value": "5.0"}),
                             step("b", "lookup_row", {"table": "depts", "column": "active", "value": "no"})])
    assert out["a"].output["count"] == 2 and out["a"].output["row"]["code"] == "A"
    assert out["b"].output["row"]["code"] == "B"


def test_lookup_steps_are_checked_on_save(admin, rkey):
    mk(admin)
    ok = {"table": "depts", "column": "code", "value": "x"}
    assert save(admin, [step("a", "lookup_row", ok)]).status_code == 201
    for cfg in ({**ok, "table": "nope"}, {**ok, "column": "nope"}, {**ok, "value": ""}, {**ok, "table": "Bad"}):
        assert save(admin, [step("a", "lookup_row", cfg)]).status_code == 422, cfg
    r = save(admin, [step("a", "lookup_row", {**ok, "value": "{{trigger.user.first_name}}"})])
    assert r.status_code == 422 and "themselves" in r.json()["detail"]        # the key picks the row: not user-editable text
    assert save(admin, [step("a", "lookup_row", {**ok, "value": "{{trigger.user.email}}"})]).status_code == 201


# ---- trust ---------------------------------------------------------------------------------------------------------------

def test_what_a_recipe_writable_table_returns_is_treated_as_user_editable(admin, rkey):
    mk(admin, name="scratch", managed=False)
    look = step("a", "lookup_row", {"table": "scratch", "column": "code", "value": "x"})
    cond = step("c", "condition", {"match": "all", "conditions": [{"left": "steps.a.output.found", "operator": "equals", "value": "true"}]})
    r = save(admin, [look, cond])
    assert r.status_code == 422 and "recipes can write" in r.json()["detail"]
    r = save(admin, [look, step("g", "add_to_group", {"group_id": 1, "user": "{{steps.a.output.row.code}}"})])
    assert r.status_code == 422
    r = save(admin, [look, step("v", "set_variable", {"name": "x", "value": "{{steps.a.output.row.code}}"})])
    assert r.status_code == 422
    r = save(admin, [look, step("l", "log", {"message": "{{steps.a.output.row.code}}"})])
    assert r.status_code == 201                                              # reading it for a log, an email or an http call is fine
    # a table that only administrators write is trusted
    mk(admin, name="trusted", managed=True)
    look2 = step("a", "lookup_row", {"table": "trusted", "column": "code", "value": "x"})
    assert save(admin, [look2, cond]).status_code == 201


def test_turning_trust_off_stops_published_decisions_from_running(db, admin, rkey):
    tid = mk(admin)
    add(admin, tid, code="ENG")
    rid = make_recipe(admin, definition("manual", [
        step("a", "lookup_row", {"table": "depts", "column": "code", "value": "ENG"}),
        step("c", "condition", {"match": "all", "conditions": [{"left": "steps.a.output.found", "operator": "equals", "value": "true"}]},
             then=[LOG("yes", "ok")])]))
    r = admin.put(f"/admin/lookup-tables/{tid}", {"admin_managed": False})
    assert r.status_code == 200 and r.json()["used_by"] == ["Recipe 1"]
    admin.post(f"/admin/recipes/{rid}/run", {})
    run_worker()
    (j,) = jobs(db, rid)
    assert j.status == "failed" and "recipes can write" in j.error
    assert "yes" not in [s.step_id for s in steps_of(db, j.id)]


# ---- the write step ----------------------------------------------------------------------------------------------------------

def test_recipes_cannot_write_an_administrator_managed_table(admin, rkey):
    mk(admin)
    r = save(admin, [step("w", "lookup_write", {"table": "depts", "action": "upsert", "values": {"code": "X"}})])
    assert r.status_code == 422 and "administrator-managed" in r.json()["detail"]


def test_add_upsert_and_delete_from_a_recipe(db, admin, rkey):
    tid = mk(admin, name="seen", managed=False)
    j, out = run(admin, db, [
        step("a", "lookup_write", {"table": "seen", "action": "add", "values": {"code": "u1", "limit": "3"}}),
        step("b", "lookup_write", {"table": "seen", "action": "upsert", "values": {"code": "u1", "limit": "4"}}),
        step("c", "lookup_write", {"table": "seen", "action": "upsert", "values": {"code": "u2", "active": "true"}}),
        step("d", "lookup_write", {"table": "seen", "action": "delete", "key": "u2"}),
        step("e", "lookup_write", {"table": "seen", "action": "delete", "key": "zzz"}),
        step("f", "lookup_row", {"table": "seen", "column": "code", "value": "u1"}),
        LOG("g", "limit={{steps.f.output.row.limit}}"),
    ])
    assert j.status == "succeeded", j.error
    assert [out[k].output["action"] for k in "abcde"] == ["inserted", "updated", "inserted", "deleted", "not_found"]
    assert out["e"].output["changed"] is False and out["g"].output["message"] == "limit=4"
    t = admin.get(f"/admin/lookup-tables/{tid}").json()
    assert t["row_count"] == 1
    assert db.query(AuditEvent).filter(AuditEvent.action == "RECIPE_LOOKUP_WRITE").count() == 5


def test_write_values_may_come_from_user_editable_text_but_stay_marked(db, admin, rkey):
    mk(admin, name="seen", managed=False)
    r = save(admin, [step("w", "lookup_write", {"table": "seen", "action": "add", "values": {"code": "{{trigger.user.first_name}}"}})])
    assert r.status_code == 201


def test_write_step_checks_columns_and_keys_on_save(admin, rkey):
    mk(admin, name="seen", managed=False)
    mk(admin, name="nokey", key=None, managed=False)
    w = lambda **c: save(admin, [step("w", "lookup_write", c)]).status_code  # noqa: E731
    assert w(table="seen", action="add", values={"code": "a"}) == 201
    assert w(table="seen", action="add", values={"nope": "a"}) == 422
    assert w(table="seen", action="add", values={"limit": "1"}) == 422                 # keyed table: the key is required
    assert w(table="seen", action="upsert", values={"limit": "1"}) == 422
    assert w(table="seen", action="add", values={}) == 422
    assert w(table="seen", action="delete", key="") == 422
    assert w(table="seen", action="delete", key="a") == 201
    assert w(table="nokey", action="upsert", values={"code": "a"}) == 422
    assert w(table="nokey", action="delete", key="a") == 422
    assert w(table="nokey", action="add", values={"code": "a"}) == 201


def test_a_bad_value_fails_the_step_and_a_test_run_writes_nothing(db, admin, rkey):
    tid = mk(admin, name="seen", managed=False)
    j, out = run(admin, db, [step("w", "lookup_write", {"table": "seen", "action": "add", "values": {"code": "a", "limit": "lots"}})])
    assert j.status == "failed" and "not a number" in j.error
    rid = make_recipe(admin, definition("manual", [step("w", "lookup_write", {"table": "seen", "action": "add", "values": {"code": "a"}})]), name="T", publish=False, enable=False)
    t = admin.post(f"/admin/recipes/{rid}/test", {})
    assert t.status_code == 200 and t.json()["status"] == "succeeded" and t.json()["steps"][0]["output"]["dry_run"] is True
    assert admin.get(f"/admin/lookup-tables/{tid}").json()["row_count"] == 0


def test_rows_stay_in_their_table(db, admin):
    a, b = mk(admin, name="one"), mk(admin, name="two")
    r = add(admin, a, code="X")
    assert admin.delete(f"/admin/lookup-tables/{b}/rows/{r['id']}").status_code == 404
    assert admin.put(f"/admin/lookup-tables/{b}/rows/{r['id']}", {"values": {"code": "Y"}}).status_code == 404
    db.expire_all()
    assert db.query(LookupRow).count() == 1 and db.query(LookupTable).count() == 2
