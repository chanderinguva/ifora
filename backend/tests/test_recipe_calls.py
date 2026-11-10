"""Callable recipes (ADR 021 s.3, WP-016): declared inputs/outputs, child jobs, guards, taint."""

import pytest

from tests.recipe_helpers import definition, jobs, make_recipe, rkey, run_worker, step, steps_of  # noqa: F401

LOG = lambda sid, msg: step(sid, "log", {"message": msg})  # noqa: E731
SIG = {"inputs": [{"name": "n", "type": "number"}], "outputs": ["double"]}


def doubler(admin, name="Doubler"):
    return make_recipe(admin, definition("call", [step("r", "return_data", {"values": {"double": "{{= number(trigger.payload.n) * 2 }}"}})], SIG), name=name)


def caller(admin, callee, inputs=None, extra=None, name="Caller", **kw):
    steps = [step("c", "call_recipe", {"recipe_id": callee, "inputs": inputs if inputs is not None else {"n": "21"}}),
             LOG("after", "got {{steps.c.output.result.double}}")] + (extra or [])
    return make_recipe(admin, {**definition("manual", steps), **kw}, name=name)


def drain(n=8):
    for _ in range(n):
        run_worker()


def start(admin, rid):
    assert admin.post(f"/admin/recipes/{rid}/run", {}).status_code == 202


def test_a_recipe_calls_another_and_uses_what_it_returns(db, admin, rkey):
    cid = doubler(admin)
    rid = caller(admin, cid)
    start(admin, rid)
    drain()
    (parent,) = jobs(db, rid)
    (child,) = jobs(db, cid)
    assert parent.status == "succeeded", parent.error
    assert child.status == "succeeded" and child.parent_job_id == parent.id and child.depth == 1
    out = {s.step_id: s.output for s in steps_of(db, parent.id) if s.status == "succeeded"}
    assert out["c"]["result"] == {"double": 42} and out["after"]["message"] == "got 42"


def test_a_test_run_runs_the_published_callee_without_waiting(db, admin, rkey):
    cid = doubler(admin)
    rid = make_recipe(admin, definition("manual", [step("c", "call_recipe", {"recipe_id": cid, "inputs": {"n": "5"}}), LOG("a", "{{steps.c.output.result.double}}")]),
                      name="Tester", publish=False, enable=False)
    r = admin.post(f"/admin/recipes/{rid}/test", {})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["status"] == "succeeded", (j.get("error"), j["steps"])
    assert [s["output"] for s in j["steps"] if s["step_id"] == "a"][0]["message"] == "10"


def test_a_failing_callee_fails_the_call_and_the_error_steps_run(db, admin, rkey):
    cid = make_recipe(admin, definition("call", [step("s", "stop", {"outcome": "failed", "message": "nope"})], {"inputs": [], "outputs": []}), name="Fails")
    rid = make_recipe(admin, {**definition("manual", [step("c", "call_recipe", {"recipe_id": cid, "inputs": {}})]),
                              "on_error": [LOG("h", "handled {{error.message}}")]}, name="Parent")
    start(admin, rid)
    drain()
    (parent,) = jobs(db, rid)
    assert parent.status == "failed" and "called recipe failed" in parent.error and "nope" in parent.error
    assert "h" in [s.step_id for s in steps_of(db, parent.id)]


def test_a_recipe_cannot_be_called_from_inside_itself(db, admin, rkey):
    sig = {"inputs": [], "outputs": []}
    aid = make_recipe(admin, definition("call", [LOG("l", "x")], sig), name="A")
    d = definition("call", [step("self", "call_recipe", {"recipe_id": aid, "inputs": {}})], sig)
    r = admin.put(f"/admin/recipes/{aid}", {"name": "A", "definition": d})
    assert r.status_code == 200, r.text
    assert admin.post(f"/admin/recipes/{aid}/publish").status_code == 200
    rid = make_recipe(admin, definition("manual", [step("c", "call_recipe", {"recipe_id": aid, "inputs": {}})]), name="B")
    start(admin, rid)
    drain(12)
    (parent,) = jobs(db, rid)
    assert parent.status == "failed" and "recursive" in parent.error


def test_calls_are_limited_to_five_levels(db, admin, rkey):
    sig = {"inputs": [], "outputs": []}
    nxt = make_recipe(admin, definition("call", [LOG("l", "leaf")], sig), name="R6")
    for i in range(5, 0, -1):
        nxt = make_recipe(admin, definition("call", [step("c", "call_recipe", {"recipe_id": nxt, "inputs": {}})], sig), name=f"R{i}")
    top = make_recipe(admin, definition("manual", [step("c", "call_recipe", {"recipe_id": nxt, "inputs": {}})]), name="R0")
    start(admin, top)
    drain(40)
    (parent,) = jobs(db, top)
    assert parent.status == "failed" and "levels deep" in parent.error


def test_save_rules(admin, rkey):
    cid = doubler(admin)
    plain = make_recipe(admin, definition("manual", [LOG("l", "x")]), name="Plain")
    unpublished = make_recipe(admin, definition("call", [LOG("l", "x")], {"inputs": [], "outputs": []}), name="Draft", publish=False, enable=False)

    def save(steps, **kw):
        return admin.post("/admin/recipes", {"name": f"S{len(str(steps))}{id(steps)}", "definition": {**definition("manual", steps), **kw}})

    call = lambda rid, inputs: step("c", "call_recipe", {"recipe_id": rid, "inputs": inputs})  # noqa: E731
    assert save([call(cid, {"n": "1"})]).status_code == 201
    assert save([call(99999, {})]).status_code == 422                          # unknown recipe
    assert save([call(plain, {})]).status_code == 422                          # not callable
    assert save([call(unpublished, {})]).status_code == 422                    # not published
    assert save([call(cid, {})]).status_code == 422                            # missing required input
    assert save([call(cid, {"n": "1", "zzz": "2"})]).status_code == 422       # unknown input
    assert save([LOG("l", "x")], on_error=[call(cid, {"n": "1"})]).status_code == 422   # not in the error steps
    assert save([call(cid, {"n": "{{trigger.user.first_name}}"})]).status_code == 422   # user-editable text


def test_return_data_rules(admin, rkey):
    def callee(steps, cfg=SIG, trig="call"):
        return admin.post("/admin/recipes", {"name": f"C{id(steps)}", "definition": definition(trig, steps, cfg)})

    ok = step("r", "return_data", {"values": {"double": "1"}})
    assert callee([ok]).status_code == 201
    assert callee([step("r", "return_data", {"values": {}})]).status_code == 422                  # must return every declared output
    assert callee([step("r", "return_data", {"values": {"double": "1", "extra": "2"}})]).status_code == 422
    assert callee([ok], {}, "manual").status_code == 422                                           # only for callable recipes
    assert callee([step("r", "return_data", {"values": {"double": "{{trigger.user.first_name}}"}})], SIG).status_code == 422
    assert admin.post("/admin/recipes", {"name": "bad", "definition": definition("call", [ok], {"outputs": ["Bad Name"]})}).status_code == 422
    dup = {"inputs": [{"name": "a"}, {"name": "a"}], "outputs": []}
    assert admin.post("/admin/recipes", {"name": "dup", "definition": definition("call", [LOG("l", "x")], dup)}).status_code == 422


def test_input_types_are_checked_when_the_call_runs(db, admin, rkey):
    cid = doubler(admin)
    rid = caller(admin, cid, inputs={"n": "not a number"}, name="Typed")
    start(admin, rid)
    drain()
    (parent,) = jobs(db, rid)
    assert parent.status == "failed" and "must be a number" in parent.error
    assert jobs(db, cid) == []


def test_meta_and_callers(admin, rkey):
    cid = doubler(admin)
    rid = caller(admin, cid)
    m = admin.get("/admin/recipes/meta").json()
    assert [c["name"] for c in m["callable_recipes"]] == ["Doubler"] and m["callable_recipes"][0]["outputs"] == ["double"]
    assert admin.get(f"/admin/recipes/{cid}/callers").json()["callers"] == [{"id": rid, "name": "Caller"}]
    assert admin.get(f"/admin/recipes/{rid}/callers").json()["callers"] == []
