"""A Handle errors block scoped to part of the flow (WP-014)."""

import httpx

from tests.recipe_helpers import T0, Remote, definition, install_remote, jobs, make_recipe, rkey, run_worker, step, steps_of  # noqa: F401

FAIL = step("call", "http_request", {"method": "GET", "url": "https://svc.example.com/"}, max_attempts=1)
LOG = lambda sid, msg="x": step(sid, "log", {"message": msg})  # noqa: E731


def block(sid, body, handler):
    return step(sid, "handle_errors", {}, then=body, **{"else": handler})


def go(db, admin, monkeypatch, steps, responses=None):
    install_remote(monkeypatch, Remote(responses or [httpx.Response(404)] * 4))
    rid = make_recipe(admin, definition("manual", steps))
    admin.post(f"/admin/recipes/{rid}/run", {})
    run_worker()
    (j,) = jobs(db, rid)
    return j, [(s.step_id, s.status) for s in steps_of(db, j.id)], {s.step_id: s for s in steps_of(db, j.id)}


def test_a_caught_error_runs_the_handler_and_the_job_carries_on(db, admin, monkeypatch):
    steps = [LOG("before"), block("b", [FAIL, LOG("skipped")], [LOG("h", "caught {{error.step_id}}: {{error.message}}")]), LOG("after")]
    j, rows, by = go(db, admin, monkeypatch, steps)
    assert j.status == "succeeded", j.error
    assert rows == [("before", "succeeded"), ("b", "succeeded"), ("call", "failed"), ("h", "succeeded"), ("after", "succeeded")]
    assert "caught call" in by["h"].output["message"]


def test_no_error_skips_the_handler(db, admin, monkeypatch):
    j, rows, _ = go(db, admin, monkeypatch, [block("b", [LOG("ok")], [LOG("h")]), LOG("after")])
    assert j.status == "succeeded" and [r[0] for r in rows] == ["b", "ok", "after"]


def test_an_error_outside_the_block_still_fails_the_job(db, admin, monkeypatch):
    j, rows, _ = go(db, admin, monkeypatch, [block("b", [LOG("ok")], [LOG("h")]), FAIL, LOG("never")])
    assert j.status == "failed" and "call" in j.error and ("never", "succeeded") not in rows


def test_inner_block_catches_first_and_a_failing_handler_reaches_the_outer_block(db, admin, monkeypatch):
    inner = block("in", [FAIL], [step("call2", "http_request", {"method": "GET", "url": "https://svc.example.com/x"}, max_attempts=1), LOG("inner_h")])
    j, rows, _ = go(db, admin, monkeypatch, [block("out", [inner, LOG("skipped")], [LOG("outer_h")]), LOG("after")])
    assert j.status == "succeeded", j.error
    names = [r[0] for r in rows]
    assert "outer_h" in names and "inner_h" not in names and "skipped" not in names and "after" in names


def test_the_recipe_level_handler_still_works_when_the_block_does_not_apply(db, admin, monkeypatch):
    install_remote(monkeypatch, Remote([httpx.Response(404)] * 2))
    d = {**definition("manual", [block("b", [LOG("ok")], [LOG("h")]), FAIL]), "on_error": [LOG("global")]}
    rid = make_recipe(admin, d)
    admin.post(f"/admin/recipes/{rid}/run", {})
    run_worker()
    (j,) = jobs(db, rid)
    assert j.status == "failed" and j.in_handler is True and ("global", "succeeded") in [(s.step_id, s.status) for s in steps_of(db, j.id)]


def test_a_failure_inside_a_loop_is_caught_and_the_loop_ends_cleanly(db, admin, monkeypatch):
    loop = step("each", "for_each_item", {"list": "{{= json_parse('[1,2]') }}", "limit": 5},
                then=[block("b", [FAIL], [LOG("h", "item {{loop.item}}")]), LOG("tail", "t{{loop.item}}")])
    j, rows, _ = go(db, admin, monkeypatch, [loop, LOG("after")], [httpx.Response(404)] * 6)
    assert j.status == "succeeded", j.error
    names = [r[0] for r in rows]
    assert names.count("h") == 2 and names.count("tail") == 2 and names[-1] == "after"


def test_save_rules(admin, monkeypatch):
    n = [0]

    def save(steps):
        n[0] += 1
        return admin.post("/admin/recipes", {"name": f"R{n[0]}", "definition": definition("manual", steps)})

    # error datapills only in the on-error steps
    r = save([block("b", [LOG("a", "{{error.message}}")], [])])
    assert r.status_code == 422 or r.status_code == 400
    assert save([block("b", [LOG("a")], [LOG("h", "{{error.message}}")])]).status_code in (200, 201)
    # no approvals, waits, loops or calls in the on-error steps
    bad = step("w", "wait", {"amount": 1, "unit": "minutes"})
    assert save([block("b", [LOG("a")], [bad])]).status_code in (400, 422)
    # what the monitored steps produce is not available afterwards (they may not have run)
    assert save([block("b", [LOG("a")], []), LOG("c", "{{steps.a.output.message}}")]).status_code in (400, 422)
    # but what ran before the block is
    assert save([LOG("a"), block("b", [LOG("m")], [LOG("h", "{{steps.a.output.message}}")]), LOG("c", "{{steps.a.output.message}}")]).status_code in (200, 201)
