"""Else-if chains: a condition whose 'otherwise' lane holds one flagged condition (WP-010)."""

import itertools

import pytest

from tests.recipe_helpers import T0, definition, jobs, make_recipe, rkey, run_worker, step, steps_of  # noqa: F401

LOG = lambda sid, msg="x": step(sid, "log", {"message": msg})  # noqa: E731
SETV = lambda mode: step("v", "set_variable", {"name": "mode", "value": mode})  # noqa: E731
n = itertools.count()


def cond(sid, value, then, other, link=False):
    c = step(sid, "condition", {"match": "all", "conditions": [{"left": "vars.mode", "operator": "equals", "value": value}]}, then=then, **{"else": other})
    if link:
        c["else_if"] = True
    return c


def chain(*pairs, last="none", links=None):
    """pairs: (value, step id) top to bottom, then a final 'otherwise' step."""
    out = [LOG(last)]
    for i, (value, sid) in reversed(list(enumerate(pairs))):
        out = [cond("c" + sid, value, [LOG(sid)], out, link=i > 0)]
    return out


def save(admin, steps):
    return admin.post("/admin/recipes", {"name": f"ei {next(n)}", "definition": definition("manual", steps)})


@pytest.mark.parametrize("mode,ran", [("a", "a"), ("b", "b"), ("c", "c"), ("zzz", "none")])
def test_exactly_one_branch_of_the_chain_runs(db, admin, rkey, mode, ran):
    rid = make_recipe(admin, definition("manual", [SETV(mode), *chain(("a", "a"), ("b", "b"), ("c", "c"))]), name=f"ei {next(n)}")
    admin.post(f"/admin/recipes/{rid}/run", {})
    run_worker()
    (j,) = jobs(db, rid)
    assert j.status == "succeeded", j.error
    done = {s.step_id for s in steps_of(db, j.id)}
    assert {"a", "b", "c", "none"} & done == {ran}


def test_long_chains_do_not_hit_the_nesting_limit(admin, rkey):
    pairs = [(str(i), f"s{i}") for i in range(8)]
    assert save(admin, [SETV("0"), *chain(*pairs)]).status_code == 201


def test_a_chain_has_a_length_limit(admin, rkey):
    pairs = [(str(i), f"s{i}") for i in range(13)]
    r = save(admin, [SETV("0"), *chain(*pairs)])
    assert r.status_code == 422 and "at most" in r.json()["detail"]


def test_the_flag_is_only_for_the_sole_condition_in_an_otherwise_lane(admin, rkey):
    flagged = cond("x", "a", [LOG("p")], [], link=True)
    assert save(admin, [SETV("a"), flagged]).status_code == 422                                            # top level
    assert save(admin, [SETV("a"), cond("c", "a", [flagged], [])]).status_code == 422                       # in the 'then' lane
    assert save(admin, [SETV("a"), cond("c", "a", [], [flagged, LOG("extra")])]).status_code == 422         # not alone
    assert save(admin, [SETV("a"), cond("c", "a", [], [{**LOG("l"), "else_if": True}])]).status_code == 422  # not a condition
    assert save(admin, [SETV("a"), cond("c", "a", [], [{**flagged, "else_if": "yes"}])]).status_code == 422
    assert save(admin, [SETV("a"), cond("c", "a", [], [flagged])]).status_code == 201


def test_a_link_still_counts_its_own_nesting_inside_its_lanes(admin, rkey):
    deep = cond("d1", "a", [cond("d2", "a", [cond("d3", "a", [LOG("z")], [])], [])], [])
    r = save(admin, [SETV("a"), cond("c", "a", [], [cond("l", "a", [deep], [], link=True)])])
    assert r.status_code == 422 and "nested" in r.json()["detail"]

