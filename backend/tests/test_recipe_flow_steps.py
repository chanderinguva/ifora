"""Variables, wait and throttle steps (ADR 021 s.3)."""

from datetime import datetime, timedelta, timezone

import pytest

from tests.recipe_helpers import definition, jobs, make_recipe, rkey, run_worker, step, steps_of  # noqa: F401

LOG = lambda sid, msg: step(sid, "log", {"message": msg})  # noqa: E731
SETV = lambda sid, name, value: step(sid, "set_variable", {"name": name, "value": value})  # noqa: E731


def now():
    return datetime.now(timezone.utc)


def save(admin, steps, **kw):
    return admin.post("/admin/recipes", {"name": "R", "definition": definition("manual", steps)})


# ---- variables ---------------------------------------------------------------------------------------------------

def test_variables_carry_values_and_keep_their_type(db, admin, rkey):
    rid = make_recipe(admin, definition("manual", [
        SETV("a", "total", "5"),
        SETV("b", "bigger", "{{= number(vars.total) + 1 }}"),
        SETV("c", "label", "n={{vars.bigger}}"),
        LOG("d", "{{vars.label}} / {{= vars.bigger * 2 }}"),
    ]))
    admin.post(f"/admin/recipes/{rid}/run", {})
    run_worker()
    (j,) = jobs(db, rid)
    assert j.status == "succeeded", j.error
    out = {s.step_id: s.output for s in steps_of(db, j.id)}
    assert out["b"]["value"] == 6 and out["c"]["value"] == "n=6" and out["d"]["message"] == "n=6 / 12"


def test_a_variable_can_be_changed_and_used_in_a_decision(db, admin, rkey):
    rid = make_recipe(admin, definition("manual", [
        SETV("a", "mode", "old"),
        SETV("b", "mode", "new"),
        step("c", "condition", {"match": "all", "conditions": [{"left": "vars.mode", "operator": "equals", "value": "new"}]},
             then=[LOG("yes", "changed")], **{"else": [LOG("no", "stale")]}),
    ]))
    admin.post(f"/admin/recipes/{rid}/run", {})
    run_worker()
    (j,) = jobs(db, rid)
    ran = [s.step_id for s in steps_of(db, j.id)]
    assert "yes" in ran and "no" not in ran


def test_a_variable_must_be_set_before_it_is_read(admin, rkey):
    r = save(admin, [LOG("a", "{{vars.later}}"), SETV("b", "later", "x")])
    assert r.status_code == 422 and "variable" in r.json()["detail"]
    assert save(admin, [SETV("b", "later", "x"), LOG("a", "{{vars.later}}")]).status_code == 201


def test_variables_cannot_launder_user_editable_text(admin, rkey):
    # first name is editable by the user; it must not be stored where a state-changing step or a decision could use it
    r = save(admin, [SETV("a", "who", "{{trigger.user.first_name}}")])
    assert r.status_code == 422
    r = save(admin, [SETV("a", "who", "{{= upper(trigger.user.last_name) }}")])
    assert r.status_code == 422
    assert save(admin, [SETV("a", "who", "{{trigger.user.email}}")]).status_code == 201


@pytest.mark.parametrize("name", ["Bad", "1a", "a-b", "", "x" * 33, "a b"])
def test_variable_names_are_restricted(admin, rkey, name):
    assert save(admin, [SETV("a", name, "x")]).status_code == 422


def test_at_most_twenty_variables_and_values_are_limited(admin, db, rkey):
    assert save(admin, [SETV(f"s{i}", f"v{i}", "x") for i in range(21)]).status_code == 422
    assert save(admin, [SETV(f"s{i}", f"v{i}", "x") for i in range(20)]).status_code == 201
    # variables together are capped (64 KB): the step that goes over fails, the worker carries on
    steps = [SETV("a", "v1", "x" * 900)] + [SETV(f"b{i}", f"w{i}", "{{vars.v1}}" * 10) for i in range(9)]
    rid = make_recipe(admin, definition("manual", steps), name="R2")
    admin.post(f"/admin/recipes/{rid}/run", {})
    run_worker()
    (j,) = jobs(db, rid)
    assert j.status == "failed" and "too large" in j.error


def test_variables_are_not_visible_in_the_error_steps(admin, rkey):
    d = definition("manual", [SETV("a", "v", "x"), LOG("b", "hi")])
    d["on_error"] = [LOG("h", "{{vars.v}}")]
    assert admin.post("/admin/recipes", {"name": "R", "definition": d}).status_code == 422


# ---- wait ------------------------------------------------------------------------------------------------------------

def test_wait_pauses_the_job_and_resumes_it_when_due(db, admin, rkey):
    rid = make_recipe(admin, definition("manual", [
        LOG("a", "before"), step("w", "wait", {"amount": 2, "unit": "minutes"}), LOG("b", "after: {{steps.w.output.waited_seconds}}")]))
    admin.post(f"/admin/recipes/{rid}/run", {})
    base = now()
    run_worker(base)
    (j,) = jobs(db, rid)
    assert j.status == "waiting" and j.approval is None
    assert [(s.step_id, s.status) for s in steps_of(db, j.id)] == [("a", "succeeded"), ("w", "waiting")]
    assert abs((j.next_run_at - (base + timedelta(minutes=2))).total_seconds()) < 2
    run_worker(base + timedelta(minutes=1))                       # not due: nothing happens
    assert jobs(db, rid)[0].status == "waiting"
    run_worker(base + timedelta(minutes=3))
    (j,) = jobs(db, rid)
    assert j.status == "succeeded", j.error
    out = {s.step_id: s.output for s in steps_of(db, j.id)}
    assert out["w"]["waited_seconds"] >= 120 and out["b"]["message"].startswith("after: ")
    assert j.paused_seconds >= 120 and "_wait" not in j.step_outputs


def test_wait_does_not_count_against_the_runtime_limit(db, admin, rkey, monkeypatch):
    from backend.app.config import settings

    monkeypatch.setattr(settings, "RECIPES_MAX_RUNTIME_SECONDS", 60)
    rid = make_recipe(admin, definition("manual", [step("w", "wait", {"amount": 1, "unit": "hours"}), LOG("b", "done")]))
    admin.post(f"/admin/recipes/{rid}/run", {})
    base = now()
    run_worker(base)
    run_worker(base + timedelta(hours=1, seconds=5))
    assert jobs(db, rid)[0].status == "succeeded"


def test_a_waiting_job_can_be_cancelled(db, admin, rkey):
    rid = make_recipe(admin, definition("manual", [step("w", "wait", {"amount": 1, "unit": "days"}), LOG("b", "never")]))
    admin.post(f"/admin/recipes/{rid}/run", {})
    run_worker()
    (j,) = jobs(db, rid)
    assert j.status == "waiting"
    assert admin.post(f"/admin/recipes/jobs/{j.id}/cancel").status_code == 200
    run_worker(now() + timedelta(days=2))
    (j,) = jobs(db, rid)
    assert j.status == "cancelled" and "b" not in [s.step_id for s in steps_of(db, j.id)]


def test_a_test_run_never_waits(db, admin, rkey):
    rid = make_recipe(admin, definition("manual", [step("w", "wait", {"amount": 7, "unit": "days"}), LOG("b", "x")]), publish=False, enable=False)
    r = admin.post(f"/admin/recipes/{rid}/test", {})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["mode"] == "dry_run" and j["status"] == "succeeded" and [x["step_id"] for x in j["steps"]] == ["w", "b"]
    assert j["steps"][0]["output"]["waited_seconds"] == 0


@pytest.mark.parametrize("cfg,ok", [
    ({"amount": 7, "unit": "days"}, True), ({"amount": 8, "unit": "days"}, False), ({"amount": 10080, "unit": "minutes"}, True),
    ({"amount": 10081, "unit": "minutes"}, False), ({"amount": 169, "unit": "hours"}, False), ({"amount": 0, "unit": "minutes"}, False),
    ({"amount": 5, "unit": "weeks"}, False), ({"amount": 5}, True), ({}, False),
])
def test_wait_limits(admin, rkey, cfg, ok):
    assert (save(admin, [step("w", "wait", cfg)]).status_code == 201) is ok


def test_wait_and_throttle_are_refused_in_the_error_steps(admin, rkey):
    for st in (step("w", "wait", {"amount": 1}), step("t", "throttle", {"max_runs": 1, "per_minutes": 1})):
        d = definition("manual", [LOG("a", "x")])
        d["on_error"] = [st]
        assert admin.post("/admin/recipes", {"name": "R", "definition": d}).status_code == 422


# ---- throttle --------------------------------------------------------------------------------------------------------

def throttle_recipe(admin, when_full="wait"):
    return make_recipe(admin, definition("manual", [
        step("t", "throttle", {"max_runs": 2, "per_minutes": 10, "when_full": when_full}), LOG("go", "through")]))


def run_n(admin, rid, n):
    for _ in range(n):
        assert admin.post(f"/admin/recipes/{rid}/run", {}).status_code in (200, 201, 202)


def test_throttle_lets_max_runs_through_and_holds_the_rest(db, admin, rkey):
    rid = throttle_recipe(admin)
    run_n(admin, rid, 3)
    base = now()
    run_worker(base)
    st = sorted(j.status for j in jobs(db, rid))
    assert st == ["succeeded", "succeeded", "waiting"]
    held = [j for j in jobs(db, rid) if j.status == "waiting"][0]
    assert held.next_run_at > base + timedelta(minutes=9)           # a slot frees when the oldest pass is 10 minutes old
    run_worker(base + timedelta(minutes=5))                         # too early: still held, and nothing is re-run
    assert [j.status for j in jobs(db, rid) if j.id == held.id] == ["waiting"]
    run_worker(base + timedelta(minutes=11))
    assert [j.status for j in jobs(db, rid)] == ["succeeded"] * 3
    rows = [s for s in steps_of(db, held.id) if s.step_id == "t"]
    assert [s.status for s in rows] == ["waiting", "succeeded"]     # one history row for the wait, one for the pass
    assert rows[1].output["waited_seconds"] >= 9 * 60


def test_throttle_stop_drops_the_extra_jobs(db, admin, rkey):
    rid = throttle_recipe(admin, "stop")
    run_n(admin, rid, 3)
    run_worker(now())
    js = jobs(db, rid)
    assert sorted(j.status for j in js) == ["cancelled", "succeeded", "succeeded"]
    dropped = [j for j in js if j.status == "cancelled"][0]
    assert "throttle" in dropped.error and "go" not in [s.step_id for s in steps_of(db, dropped.id)]
    # a dropped job is not a pass: after the window two more get through, not zero
    run_n(admin, rid, 2)
    run_worker(now() + timedelta(minutes=11))
    assert sorted(j.status for j in jobs(db, rid)).count("succeeded") == 4


def test_throttle_is_per_step_and_per_recipe(db, admin, rkey):
    a, b = throttle_recipe(admin), make_recipe(admin, definition("manual", [
        step("t", "throttle", {"max_runs": 1, "per_minutes": 10, "when_full": "wait"}), LOG("go", "x")]), name="Other")
    run_n(admin, a, 2)
    run_n(admin, b, 2)
    run_worker(now())
    assert sorted(j.status for j in jobs(db, a)) == ["succeeded", "succeeded"]
    assert sorted(j.status for j in jobs(db, b)) == ["succeeded", "waiting"]


def test_a_waiting_throttle_does_not_use_up_the_step_budget(db, admin, rkey):
    rid = make_recipe(admin, definition("manual", [
        step("t", "throttle", {"max_runs": 1, "per_minutes": 60, "when_full": "wait"}), LOG("go", "x")]))
    run_n(admin, rid, 2)
    base = now()
    run_worker(base)
    held = [j for j in jobs(db, rid) if j.status == "waiting"][0]
    n = held.executed_steps
    run_worker(base + timedelta(minutes=30))
    assert jobs(db, rid)[1].executed_steps == n


@pytest.mark.parametrize("cfg,ok", [
    ({"max_runs": 1, "per_minutes": 1}, True), ({"max_runs": 1000, "per_minutes": 1440, "when_full": "stop"}, True),
    ({"max_runs": 0, "per_minutes": 1}, False), ({"max_runs": 1001, "per_minutes": 1}, False),
    ({"max_runs": 1, "per_minutes": 1441}, False), ({"max_runs": 1, "per_minutes": 1, "when_full": "drop"}, False), ({"max_runs": 1}, False),
])
def test_throttle_limits(admin, rkey, cfg, ok):
    assert (save(admin, [step("t", "throttle", cfg)]).status_code == 201) is ok
