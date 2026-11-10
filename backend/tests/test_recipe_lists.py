"""List functions in formulas and the 'for each item' step (WP-011, WP-012)."""

import pytest

from backend.app.recipes import templates as tpl
from tests.recipe_helpers import definition, jobs, make_recipe, rkey, run_worker, step, steps_of  # noqa: F401

CTX = {"trigger": {"payload": {"nums": [3, 1, 2, 3], "nested": [[1, 2], [3]], "rows": [{"a": 1}, {"a": 2}], "gaps": [1, None, "", 2]}}}


def run(src):
    return tpl.render("{{= " + src + " }}", CTX)


@pytest.mark.parametrize("src,want", [
    ("sum(trigger.payload.nums)", 9), ("sum([])", 0), ("index(trigger.payload.nums, 3)", 0), ("index(trigger.payload.nums, 9)", None),
    ("reverse(trigger.payload.nums)", [3, 2, 1, 3]), ("uniq(trigger.payload.nums)", [3, 1, 2]),
    ("flatten(trigger.payload.nested)", [1, 2, 3]), ("compact(trigger.payload.gaps)", [1, "", 2]),
    ("concat([1], [2, 3])", [1, 2, 3]), ("pluck(trigger.payload.rows, \"a\")", [1, 2]),
    ("smart_join(trigger.payload.gaps, \", \")", "1, 2"),
    ("min(trigger.payload.nums)", 1), ("max(trigger.payload.nums)", 3), ("min([])", None), ("min(4, 2)", 2),
])
def test_list_functions(src, want):
    assert run(src) == want


def save(admin, steps):
    return admin.post("/admin/recipes", {"name": "R", "definition": definition("manual", steps)})


def loop(items="{{= json_parse('[1,2,3]') }}", limit=50, body=None):
    return step("each", "for_each_item", {"list": items, "limit": limit},
                then=body or [step("l", "log", {"message": "i={{loop.index}}/{{loop.total}} v={{loop.item}}"})])


def go(db, admin, steps):
    rid = make_recipe(admin, definition("manual", steps))
    admin.post(f"/admin/recipes/{rid}/run", {})
    run_worker()
    (j,) = jobs(db, rid)
    return j, [s for s in steps_of(db, j.id)]


def test_loop_runs_the_body_for_each_item(db, admin, rkey):
    j, ss = go(db, admin, [loop()])
    assert j.status == "succeeded", j.error
    assert [s.output["message"] for s in ss if s.step_id == "l"] == ["i=1/3 v=1", "i=2/3 v=2", "i=3/3 v=3"]


def test_loop_items_can_be_objects(db, admin, rkey):
    j, ss = go(db, admin, [loop('{{= json_parse(\'[{"n": "x"}, {"n": "y"}]\') }}',
                                body=[step("l", "log", {"message": "{{loop.item.n}}"})])])
    assert j.status == "succeeded", j.error
    assert [s.output["message"] for s in ss if s.step_id == "l"] == ["x", "y"]


def test_empty_list_skips_the_body(db, admin, rkey):
    j, ss = go(db, admin, [loop("{{= json_parse('[]') }}"), step("after", "log", {"message": "done"})])
    assert j.status == "succeeded", j.error
    ran = [s.step_id for s in ss]
    assert "l" not in ran and "after" in ran


def test_non_list_fails_the_step(db, admin, rkey):
    j, _ = go(db, admin, [loop("{{= upper('abc') }}")])
    assert j.status == "failed" and "list" in j.error


def test_over_limit_fails_instead_of_skipping(db, admin, rkey):
    j, ss = go(db, admin, [loop(limit=2)])
    assert j.status == "failed" and "at most 2" in j.error
    assert not [s for s in ss if s.step_id == "l"]


def test_save_rules(admin, rkey):
    body = [step("l", "log", {"message": "x"})]
    assert save(admin, [loop()]).status_code == 201
    assert save(admin, [loop(body=[loop(body=body)])]).status_code == 422                    # no nesting
    assert save(admin, [step("l", "log", {"message": "{{loop.item}}"})]).status_code == 422  # outside a loop
    assert save(admin, [loop(body=[step("l", "log", {"message": "{{loop.user.email}}"})])]).status_code == 422
    assert save(admin, [loop(limit=101)]).status_code == 422
    assert save(admin, [loop("")]).status_code == 422


def test_member_loop_does_not_offer_item(admin, rkey):
    from tests.recipe_helpers import new_group
    g = new_group(admin)
    r = save(admin, [step("a", "for_each_member", {"group_id": g}, then=[step("l", "log", {"message": "{{loop.item}}"})])])
    assert r.status_code == 422


def test_a_list_cannot_come_from_user_editable_text(admin, rkey):
    r = save(admin, [loop("{{= split(trigger.user.first_name, ',') }}")])
    assert r.status_code == 422
