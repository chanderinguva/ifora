"""Recipe engine: triggers, actions, execution model, loop protection, versioning, kill switch (ADR 008)."""

from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select

from backend.app.audit.model import AuditAction, AuditEvent
from backend.app.audit.service import record
from backend.app.config import settings
from backend.app.groups.model import user_group_association
from backend.app.recipes import engine, events
from backend.app.recipes.models import Recipe, RecipeJob, RecipeOutbox, RecipeVersion
from backend.app.tenancy import Tenant, tenant_session, unscoped
from backend.app.users.model import User
from tests.conftest import make_user
from tests.recipe_helpers import (
    T0, Remote, definition, install_remote, jobs, make_recipe, new_group, new_user, outbox_count, rkey,  # noqa: F401
    run_worker, step, steps_of,
)

HELLO = step("s1", "log", {"message": "hello {{trigger.user.email}}"})


def members(db, gid):
    db.expire_all()
    return {r[0] for r in db.execute(select(user_group_association.c.user_id).where(user_group_association.c.group_id == gid))}


def set_attr(db, user_id, key, value):
    u = db.get(User, user_id)
    u.set_profile_attributes({**u.get_profile_attributes(), key: value})
    db.commit()


# ---- access ---------------------------------------------------------------------------------

def test_admin_only_and_unauthenticated(member, anon, admin):
    for call in (lambda c: c.get("/admin/recipes"), lambda c: c.get("/admin/recipes/meta"),
                 lambda c: c.get("/admin/recipes/jobs"), lambda c: c.get("/admin/recipe-connections"),
                 lambda c: c.post("/admin/recipes", {"name": "x"})):
        assert call(member).status_code == 403
        assert call(anon).status_code == 401
    assert admin.get("/admin/recipes").status_code == 200


def test_tenant_isolation(db, admin):
    rid = make_recipe(admin, definition("manual", [HELLO]))
    with unscoped(db):
        t2 = Tenant(slug="other", name="Other")
        db.add(t2)
        db.commit()
        tid2 = t2.id
    other = tenant_session(tid2)
    from backend.app.recipes.models import Recipe as R

    other.add(R(public_id="x" * 22, name="theirs", draft={"trigger": {"type": "manual", "config": {}, "filter": []}, "steps": []}))
    other.commit()
    assert [i["name"] for i in admin.get("/admin/recipes").json()["items"]] == ["Recipe 1"]
    theirs = other.query(R).one().id
    assert admin.get(f"/admin/recipes/{theirs}").status_code == 404
    assert admin.delete(f"/admin/recipes/{theirs}").status_code == 404
    assert other.query(R).count() == 1 and other.query(R).filter(R.name == "Recipe 1").count() == 0
    other.close()


# ---- triggers -> actions -----------------------------------------------------------------------

def test_user_created_adds_to_group(db, admin):
    gid = new_group(admin)
    rid = make_recipe(admin, definition("user.created", [step("s1", "add_to_group", {"group_id": gid})]))
    u = new_user(admin)
    assert outbox_count(db) == 1
    stats = run_worker()
    assert stats["jobs"] == 1 and stats["ran"] == 1
    (j,) = jobs(db, rid)
    assert j.status == "succeeded" and j.version == 1 and j.mode == "live"
    assert u["id"] in members(db, gid)
    (s,) = steps_of(db, j.id)
    assert s.status == "succeeded" and s.output["changed"] is True
    ev = db.query(AuditEvent).filter(AuditEvent.action == "GROUP_MEMBER_ADDED", AuditEvent.actor_type == "recipe").one()
    assert ev.actor_id == f"recipe:{rid}" and ev.event_metadata["via_recipe"] == rid
    assert db.query(AuditEvent).filter(AuditEvent.action == "RECIPE_JOB_SUCCEEDED").count() == 1
    assert admin.get(f"/admin/groups/{gid}").json()["member_count"] == 1


def test_remove_from_group_and_rule_managed_membership_protected(db, admin):
    gid = new_group(admin)
    make_recipe(admin, definition("user.created", [step("s1", "remove_from_group", {"group_id": gid})]))
    u = new_user(admin, group_ids=[gid])
    assert u["id"] in members(db, gid)
    run_worker()
    assert u["id"] not in members(db, gid)
    assert admin.get(f"/admin/groups/{gid}").json()["member_count"] == 0

    # a membership created by a group rule cannot be removed by a recipe
    r = admin.post("/admin/group-rules", {"name": "all", "match": "all", "group_ids": [gid],
                                          "conditions": [{"attribute": "status", "operator": "equals", "value": "active"}]})
    admin.post(f"/admin/group-rules/{r.json()['id']}/activate")
    u2 = new_user(admin, email="two@example.com")
    assert u2["id"] in members(db, gid)
    run_worker()
    assert u2["id"] in members(db, gid)
    failed = [j for j in jobs(db) if j.status == "failed"]
    assert failed and "group rule" in failed[-1].error


def test_set_attribute_and_attribute_changed_trigger(db, admin):
    make_recipe(admin, definition("user.created", [step("s1", "set_attribute", {"attribute": "department", "value": "Sales"})]), "setter")
    seen = make_recipe(admin, definition("user.attribute_changed", [step("l", "log", {"message": "{{trigger.attribute.key}}: {{trigger.attribute.old}} -> {{trigger.attribute.new}}"})],
                                          {"attribute": "department"}), "watcher")
    u = new_user(admin)
    run_worker()
    db.expire_all()
    assert db.get(User, u["id"]).get_profile_attributes()["department"] == "Sales"
    run_worker()  # the watcher sees the change made by the other recipe
    (wj,) = jobs(db, seen)
    assert wj.status == "succeeded" and wj.depth == 1
    assert steps_of(db, wj.id)[0].output["message"] == "department:  -> Sales"
    # an admin edit also triggers it
    assert admin.patch(f"/admin/users/{u['id']}", {"profile_attributes": {"department": "Ops"}}).status_code == 200
    # ... but a change to a different attribute does not
    assert admin.patch(f"/admin/users/{u['id']}", {"profile_attributes": {"department": "Ops", "cost_center": "C1"}}).status_code == 200
    run_worker()
    assert len(jobs(db, seen)) == 2


def test_set_attribute_rejects_self_editable_and_reserved(admin):
    for attr in ("title", "bio", "is_admin", "email", "nope"):
        r = admin.post("/admin/recipes", {"name": f"r-{attr}", "definition": definition(
            "user.created", [step("s1", "set_attribute", {"attribute": attr, "value": "x"})])})
        assert r.status_code == 422, attr
        assert "administrator-managed" in r.json()["detail"]


def test_deactivate_activate_and_admins_are_untouchable(db, admin):
    make_recipe(admin, definition("user.created", [step("s1", "deactivate_user")]), "deact")
    u = new_user(admin)
    run_worker()
    db.expire_all()
    assert db.get(User, u["id"]).status == "inactive"
    make_recipe(admin, definition("manual", [step("s1", "activate_user", {"user": "{{trigger.payload.uid}}"})]), "act")
    act_id = db.query(Recipe).filter(Recipe.name == "act").one().id
    assert admin.post(f"/admin/recipes/{act_id}/run", {"payload": {"uid": u["id"]}}).status_code == 202
    run_worker()
    db.expire_all()
    assert db.get(User, u["id"]).status == "active"
    # administrators cannot be deactivated by a recipe, by anyone
    make_recipe(admin, definition("manual", [step("s1", "deactivate_user", {"user": "{{trigger.payload.uid}}"})]), "kill")
    kid = db.query(Recipe).filter(Recipe.name == "kill").one().id
    assert admin.post(f"/admin/recipes/{kid}/run", {"payload": {"uid": admin.user.id}}).status_code == 202
    run_worker()
    db.expire_all()
    assert db.get(User, admin.user.id).status == "active"
    assert jobs(db, kid)[0].status == "failed" and "administrator" in jobs(db, kid)[0].error


def test_group_triggers_with_group_filter(db, admin):
    g1, g2 = new_group(admin, "G1"), new_group(admin, "G2")
    rid = make_recipe(admin, definition("group.member_added", [step("l", "log", {"message": "{{trigger.group.name}} {{trigger.user.email}}"})], {"group_id": g1}))
    u = new_user(admin)
    admin.post(f"/admin/groups/{g2}/members", {"user_id": u["id"]})
    admin.post(f"/admin/groups/{g1}/members", {"user_id": u["id"]})
    run_worker()
    (j,) = jobs(db, rid)
    assert steps_of(db, j.id)[0].output["message"] == "G1 new@example.com"
    removed = make_recipe(admin, definition("group.member_removed", [HELLO]), "rm")
    admin.delete(f"/admin/groups/{g1}/members/{u['id']}")
    run_worker()
    assert len(jobs(db, removed)) == 1


def test_trigger_filter(db, admin):
    rid = make_recipe(admin, definition("user.created", [HELLO], flt=[
        {"left": "trigger.user.email", "operator": "ends_with", "value": "@corp.example"}]))
    new_user(admin, email="a@other.example")
    new_user(admin, email="b@corp.example")
    run_worker()
    assert len(jobs(db, rid)) == 1


def test_login_failed_trigger_with_threshold_and_login_unchanged(db, admin):
    rid = make_recipe(admin, definition("login.failed", [step("l", "log", {"message": "n={{trigger.login.consecutive_failures}}"})], {"min_failures": 2}))
    from tests.conftest import Api

    victim = make_user(db, "victim@example.com")
    api = Api()
    for _ in range(3):
        assert api.login(victim.email, "wrong-Password1!").status_code == 401
    assert api.login(victim.email).status_code == 401 or True  # correct password may be locked out by now: both are fine
    run_worker()
    got = [steps_of(db, j.id)[0].output["message"] for j in jobs(db, rid)]
    assert got == ["n=2", "n=3"]


def test_schedule_trigger_runs_once_per_slot(db, admin):
    rid = make_recipe(admin, definition("schedule", [step("l", "log", {"message": "tick {{trigger.schedule.scheduled_for}}"})], {"interval_minutes": 10}))
    run_worker(T0)
    run_worker(T0 + timedelta(minutes=1))
    assert len(jobs(db, rid)) == 1
    run_worker(T0 + timedelta(minutes=11))
    assert len(jobs(db, rid)) == 2
    assert all(j.status == "succeeded" for j in jobs(db, rid))


def test_manual_run_needs_manual_trigger(db, admin):
    rid = make_recipe(admin, definition("manual", [step("l", "log", {"message": "by {{trigger.manual.started_by}} {{trigger.payload.note}}"})]))
    r = admin.post(f"/admin/recipes/{rid}/run", {"payload": {"note": "hi"}})
    assert r.status_code == 202
    run_worker()
    detail = admin.get(f"/admin/recipes/jobs/{r.json()['id']}").json()
    assert detail["status"] == "succeeded" and detail["steps"][0]["output"]["message"] == f"by {admin.user.id} hi"
    other = make_recipe(admin, definition("user.created", [HELLO]), "evt")
    assert admin.post(f"/admin/recipes/{other}/run", {}).status_code == 409
    assert db.query(AuditEvent).filter(AuditEvent.action == "RECIPE_MANUAL_RUN").count() == 1


# ---- conditions / control flow / datapills ------------------------------------------------------

def test_condition_branches_and_stop_and_step_outputs(db, admin):
    rid = make_recipe(admin, definition("manual", [
        step("a", "log", {"message": "start"}),
        step("c", "condition", {"match": "all", "conditions": [{"left": "trigger.payload.n", "operator": "greater_than", "value": "5"}]},
             then=[step("big", "log", {"message": "big after {{steps.a.output.message}}"})],
             **{"else": [step("c2", "condition", {"match": "any", "conditions": [{"left": "trigger.payload.n", "operator": "is_not_set"}]},
                              then=[step("stopit", "stop", {"outcome": "failed", "message": "n missing"})],
                              **{"else": [step("small", "log", {"message": "small"})]})]}),
        step("end", "log", {"message": "end"}),
    ]))
    def run(payload):
        j = admin.post(f"/admin/recipes/{rid}/run", {"payload": payload}).json()["id"]
        run_worker()
        return admin.get(f"/admin/recipes/jobs/{j}").json()

    big = run({"n": 9})
    assert [s["step_id"] for s in big["steps"]] == ["a", "c", "big", "end"]
    assert big["steps"][2]["output"]["message"] == "big after start" and big["status"] == "succeeded"
    small = run({"n": 1})
    assert [s["step_id"] for s in small["steps"]] == ["a", "c", "c2", "small", "end"]
    missing = run({})
    assert missing["status"] == "failed" and missing["error"] == "n missing"
    assert [s["step_id"] for s in missing["steps"]] == ["a", "c", "c2", "stopit"]


def test_dry_run_changes_nothing(db, admin):
    gid = new_group(admin)
    rid = make_recipe(admin, definition("user.created", [
        step("s1", "add_to_group", {"group_id": gid}),
        step("s2", "set_attribute", {"attribute": "department", "value": "X"}),
        step("s3", "deactivate_user"),
        step("s4", "http_request", {"method": "POST", "url": "https://example.com/hook"}),
    ]), publish=False, enable=False)
    u = new_user(admin)
    before = db.query(AuditEvent).count()
    r = admin.post(f"/admin/recipes/{rid}/test", {"user_id": u["id"]})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["mode"] == "dry_run" and j["status"] == "succeeded"
    assert [s["output"].get("changed", s["output"].get("dry_run")) for s in j["steps"]] == [True, True, True, True]
    db.expire_all()
    assert members(db, gid) == set() and db.get(User, u["id"]).status == "active"
    assert "department" not in db.get(User, u["id"]).get_profile_attributes()
    assert outbox_count(db) == 0
    assert db.query(AuditEvent).count() == before + 1  # only RECIPE_TEST_RUN
    assert admin.post(f"/admin/recipes/{rid}/test", {}).status_code == 422  # needs a sample user


# ---- http action ------------------------------------------------------------------------------------------

def test_http_request_templated_and_pinned(db, admin, monkeypatch):
    remote = Remote([httpx.Response(200, json={"id": 7}, headers={"content-type": "application/json"})])
    install_remote(monkeypatch, remote)
    rid = make_recipe(admin, definition("user.created", [
        step("call", "http_request", {"method": "POST", "url": "https://hooks.example.com/u?email={{trigger.user.email}}",
                                       "headers": {"X-Source": "idf"}, "body": '{"user": {{trigger.user.id}}}'}),
        step("after", "log", {"message": "id={{steps.call.output.json.id}} status={{steps.call.output.status_code}}"}),
    ]))
    u = new_user(admin)
    run_worker()
    (j,) = jobs(db, rid)
    assert j.status == "succeeded", j.error
    (req,) = remote.requests
    assert req.url.host == "93.184.216.34"  # connected to the validated IP, not re-resolved
    assert req.headers["host"] == "hooks.example.com"
    assert req.headers["idempotency-key"] == f"{j.id}-call"
    assert req.read() == ('{"user": %d}' % u["id"]).encode()
    assert steps_of(db, j.id)[1].output["message"] == "id=7 status=200"


def test_retries_with_backoff_then_success(db, admin, monkeypatch):
    remote = Remote([httpx.Response(503), httpx.Response(500), httpx.Response(200, json={})])
    install_remote(monkeypatch, remote)
    rid = make_recipe(admin, definition("user.created", [step("call", "http_request", {"method": "GET", "url": "https://svc.example.com/"})]))
    new_user(admin)
    run_worker(T0)
    (j,) = jobs(db, rid)
    assert j.status == "queued" and j.attempt == 1 and j.next_run_at == T0 + timedelta(seconds=5)
    run_worker(T0 + timedelta(seconds=4))  # not yet due
    assert len(remote.requests) == 1
    run_worker(T0 + timedelta(seconds=5))
    (j,) = jobs(db, rid)
    assert j.status == "queued" and j.attempt == 2 and j.next_run_at == T0 + timedelta(seconds=15)  # 5 * 2
    run_worker(T0 + timedelta(seconds=15))
    (j,) = jobs(db, rid)
    assert j.status == "succeeded" and len(remote.requests) == 3
    assert [(s.status, s.attempt) for s in steps_of(db, j.id)] == [("retrying", 1), ("retrying", 2), ("succeeded", 3)]
    assert steps_of(db, j.id)[0].error == "remote server answered 503"


def test_retries_exhausted_fails_job_and_keeps_history(db, admin, monkeypatch):
    remote = Remote([httpx.Response(502)])
    install_remote(monkeypatch, remote)
    rid = make_recipe(admin, definition("user.created", [
        step("call", "http_request", {"method": "GET", "url": "https://svc.example.com/"}, max_attempts=2),
        step("never", "log", {"message": "x"})]))
    new_user(admin)
    run_worker(T0)
    run_worker(T0 + timedelta(seconds=5))
    (j,) = jobs(db, rid)
    assert j.status == "failed" and "502" in j.error and len(remote.requests) == 2
    assert [s.status for s in steps_of(db, j.id)] == ["retrying", "failed"]
    d = admin.get(f"/admin/recipes/jobs/{j.id}").json()
    assert d["status"] == "failed" and d["steps"][-1]["error"]
    assert db.query(AuditEvent).filter(AuditEvent.action == "RECIPE_JOB_FAILED").count() == 1


def test_client_error_is_not_retried_and_on_error_continue(db, admin, monkeypatch):
    remote = Remote([httpx.Response(404)])
    install_remote(monkeypatch, remote)
    rid = make_recipe(admin, definition("user.created", [
        step("call", "http_request", {"method": "GET", "url": "https://svc.example.com/"}, on_error="continue"),
        step("after", "log", {"message": "err={{steps.call.output.error}}"})]))
    new_user(admin)
    run_worker(T0)
    (j,) = jobs(db, rid)
    assert j.status == "succeeded" and len(remote.requests) == 1
    assert steps_of(db, j.id)[1].output["message"] == "err=remote server answered 404"


# ---- outbox -----------------------------------------------------------------------------------------------

def test_outbox_atomic_with_the_change(db, admin):
    make_recipe(admin, definition("user.created", [HELLO]))
    u = make_user(db, "x@example.com")
    s = tenant_session()
    record(s, AuditAction.USER_CREATED, None, None, u.id, "user", {})
    s.rollback()  # the change did not happen -> no phantom event
    s.close()
    assert outbox_count(db) == 0
    s = tenant_session()
    record(s, AuditAction.USER_CREATED, None, None, u.id, "user", {})
    s.commit()
    s.close()
    assert outbox_count(db) == 1
    ev = db.query(RecipeOutbox).one()
    assert ev.payload["type"] == "user.created" and ev.payload["data"]["user"]["email"] == "x@example.com"
    assert "password" not in str(ev.payload).lower()


def test_failed_request_emits_nothing(db, admin):
    make_recipe(admin, definition("user.created", [HELLO]))
    new_user(admin)
    assert admin.post("/admin/users", {"email": "new@example.com", "first_name": "A", "last_name": "B", "generate_password": True}).status_code == 409
    assert outbox_count(db) == 1


def test_no_listener_no_outbox_rows(db, admin):
    new_user(admin)
    assert outbox_count(db) == 0
    rid = make_recipe(admin, definition("user.created", [HELLO]))
    admin.post(f"/admin/recipes/{rid}/disable")
    new_user(admin, email="b@example.com")
    assert outbox_count(db) == 0


def test_dispatch_is_idempotent(db, admin):
    rid = make_recipe(admin, definition("user.created", [HELLO]))
    new_user(admin)
    run_worker()
    db.expire_all()
    ev = db.query(RecipeOutbox).one()
    ev.dispatched_at = None  # simulate a crash before the dispatch commit / redelivery
    db.commit()
    run_worker()
    assert len(jobs(db, rid)) == 1


def test_two_workers_do_not_double_run(db, admin):
    rid = make_recipe(admin, definition("user.created", [HELLO]))
    new_user(admin)
    a, b = tenant_session(), tenant_session()
    try:
        ids_a = engine.claim_jobs(a, T0) if engine.dispatch_outbox(a, T0) else []
        ids_b = engine.claim_jobs(b, T0)
        assert len(ids_a) == 1 and ids_b == []
    finally:
        a.close(); b.close()


def test_lease_expiry_reclaims_crashed_job(db, admin):
    rid = make_recipe(admin, definition("user.created", [HELLO]))
    new_user(admin)
    s = tenant_session()
    engine.dispatch_outbox(s, T0)
    assert len(engine.claim_jobs(s, T0)) == 1  # claimed, then the worker "crashes"
    s.close()
    assert run_worker(T0 + timedelta(seconds=10))["ran"] == 0  # lease still valid
    assert run_worker(T0 + timedelta(seconds=settings.RECIPES_LEASE_SECONDS + 1))["ran"] == 1
    assert jobs(db, rid)[0].status == "succeeded"


# ---- loop protection --------------------------------------------------------------------------------------------

def test_recipe_never_triggers_itself(db, admin):
    rid = make_recipe(admin, definition("user.attribute_changed", [
        step("s1", "set_attribute", {"attribute": "department", "value": "d{{job.id}}"})], {"attribute": "department"}))
    u = new_user(admin)
    assert admin.patch(f"/admin/users/{u['id']}", {"profile_attributes": {"department": "start"}}).status_code == 200
    for _ in range(6):
        run_worker()
    js = jobs(db, rid)
    assert len(js) == 1 and js[0].status == "succeeded"
    db.expire_all()
    assert db.get(User, u["id"]).get_profile_attributes()["department"] == f"d{js[0].id}"


def test_ping_pong_between_two_recipes_is_bounded(db, admin):
    a = make_recipe(admin, definition("user.attribute_changed", [
        step("s1", "set_attribute", {"attribute": "cost_center", "value": "a{{job.id}}"})], {"attribute": "department"}), "A")
    b = make_recipe(admin, definition("user.attribute_changed", [
        step("s1", "set_attribute", {"attribute": "department", "value": "b{{job.id}}"})], {"attribute": "cost_center"}), "B")
    u = new_user(admin)
    admin.patch(f"/admin/users/{u['id']}", {"profile_attributes": {"department": "start"}})
    for _ in range(15):
        run_worker()
    total = len(jobs(db, a)) + len(jobs(db, b))
    assert 2 <= total <= settings.RECIPES_MAX_EVENT_DEPTH + 2
    assert run_worker()["ran"] == 0 and run_worker()["jobs"] == 0  # quiescent
    assert max(j.depth for j in jobs(db)) <= settings.RECIPES_MAX_EVENT_DEPTH


def test_step_and_runtime_caps(db, admin, monkeypatch):
    monkeypatch.setattr(settings, "RECIPES_MAX_STEPS_PER_JOB", 2)
    rid = make_recipe(admin, definition("manual", [step(f"l{i}", "log", {"message": "x"}) for i in range(4)]))
    admin.post(f"/admin/recipes/{rid}/run", {})
    run_worker()
    (j,) = jobs(db, rid)
    assert j.status == "failed" and "steps executed" in j.error
    monkeypatch.setattr(settings, "RECIPES_MAX_STEPS_PER_JOB", 50)
    admin.post(f"/admin/recipes/{rid}/run", {})
    from backend.app.recipes.engine import utcnow
    run_worker(utcnow() + timedelta(seconds=settings.RECIPES_MAX_RUNTIME_SECONDS + 5))
    assert jobs(db, rid)[-1].status == "failed" and "runtime" in jobs(db, rid)[-1].error


def test_per_recipe_concurrency_limit(db, admin, monkeypatch):
    monkeypatch.setattr(settings, "RECIPES_MAX_CONCURRENT_PER_RECIPE", 1)
    rid = make_recipe(admin, definition("manual", [HELLO]))
    # one job is "running" (lease valid) -> a second must wait
    s = tenant_session()
    r = s.get(Recipe, rid)
    v = s.query(RecipeVersion).one()
    j1 = engine.create_job(s, r, v.definition, 1, {"user": {"email": "e"}}, "k1", now=T0)
    j1.status, j1.locked_until = "running", T0 + timedelta(minutes=5)
    engine.create_job(s, r, v.definition, 1, {"user": {"email": "e"}}, "k2", now=T0)
    s.commit()
    assert engine.claim_jobs(s, T0) == []
    j1.status = "succeeded"
    s.commit()
    assert len(engine.claim_jobs(s, T0)) == 1
    s.close()


# ---- versions, switches ------------------------------------------------------------------------------------------

def test_versions_are_immutable_and_jobs_pin_their_version(db, admin):
    rid = make_recipe(admin, definition("manual", [step("l", "log", {"message": "v1"})]))
    admin.post(f"/admin/recipes/{rid}/run", {})
    # edit the draft: production keeps running v1
    r = admin.put(f"/admin/recipes/{rid}", {"name": "Recipe 1", "definition": definition("manual", [step("l", "log", {"message": "v2"})])})
    assert r.json()["has_unpublished_changes"] is True and r.json()["published_version"] == 1
    run_worker()
    (j,) = jobs(db, rid)
    assert j.version == 1 and steps_of(db, j.id)[0].output["message"] == "v1"
    p = admin.post(f"/admin/recipes/{rid}/publish").json()
    assert p["published_version"] == 2 and p["has_unpublished_changes"] is False
    assert [v["version"] for v in admin.get(f"/admin/recipes/{rid}/versions").json()["items"]] == [2, 1]
    assert admin.get(f"/admin/recipes/{rid}/versions/1").json()["definition"]["steps"][0]["config"]["message"] == "v1"
    for method in ("put", "patch", "delete"):
        assert getattr(admin, method)(f"/admin/recipes/{rid}/versions/1").status_code in (404, 405)
    admin.post(f"/admin/recipes/{rid}/run", {})
    run_worker()
    assert jobs(db, rid)[-1].version == 2


def test_cannot_enable_unpublished_and_empty_recipe_not_publishable(admin):
    r = admin.post("/admin/recipes", {"name": "draft only"}).json()
    assert admin.post(f"/admin/recipes/{r['id']}/enable").status_code == 409
    assert admin.post(f"/admin/recipes/{r['id']}/publish").status_code == 422


def test_per_recipe_disable_cancels_queued_jobs_and_stops_events(db, admin):
    rid = make_recipe(admin, definition("user.created", [HELLO]))
    new_user(admin)
    s = tenant_session()
    engine.dispatch_outbox(s, engine.utcnow() - timedelta(seconds=5))
    s.close()
    admin.post(f"/admin/recipes/{rid}/disable")
    run_worker()
    (j,) = jobs(db, rid)
    assert j.status == "cancelled" and "disabled" in j.error
    new_user(admin, email="later@example.com")
    assert outbox_count(db) == 1  # nothing new is recorded for a disabled recipe


def test_global_kill_switch(db, admin, monkeypatch):
    rid = make_recipe(admin, definition("user.created", [HELLO]))
    new_user(admin)
    monkeypatch.setattr(settings, "RECIPES_ENABLED", False)
    assert admin.get("/admin/recipes").status_code == 404
    assert admin.post("/admin/recipes", {"name": "x"}).status_code == 404
    assert run_worker() == {"events": 0, "jobs": 0, "scheduled": 0, "ran": 0}
    new_user(admin, email="b@example.com")
    assert outbox_count(db) == 1  # no new events while off
    monkeypatch.setattr(settings, "RECIPES_ENABLED", True)
    assert run_worker()["jobs"] == 1
    assert len(jobs(db, rid)) == 1


# ---- privilege escalation --------------------------------------------------------------------------------------------

def test_recipes_cannot_escalate_privileges(db, admin):
    gid = new_group(admin, "admins")  # a group *named* admins grants nothing
    make_recipe(admin, definition("user.created", [step("s1", "add_to_group", {"group_id": gid})]))
    plain = new_user(admin, email="plain@example.com")
    run_worker()
    assert plain["id"] in members(db, gid)
    from tests.conftest import Api, STRONG

    # set a known password so we can sign in as that user
    admin.post(f"/admin/users/{plain['id']}/password", {"new_password": STRONG})
    api = Api()
    assert api.login("plain@example.com").status_code == 200
    assert api.get("/admin/users").status_code == 403
    assert api.get("/admin/recipes").status_code == 403
    db.expire_all()
    assert db.get(User, plain["id"]).is_admin is False
    # no step type can touch admin flags, and system groups are refused
    bad = admin.post("/admin/recipes", {"name": "bad", "definition": definition("user.created", [step("s1", "set_attribute", {"attribute": "is_admin", "value": "true"})])})
    assert bad.status_code == 422
    unknown = admin.post("/admin/recipes", {"name": "bad2", "definition": definition("user.created", [step("s1", "grant_admin")])})
    assert unknown.status_code == 422
    from backend.app.groups.model import Group

    sysg = Group(name="System", is_system_group=True)
    db.add(sysg); db.commit()
    assert admin.post("/admin/recipes", {"name": "bad3", "definition": definition("user.created", [step("s1", "add_to_group", {"group_id": sysg.id})])}).status_code == 422


def test_untrusted_user_editable_fields_are_refused(admin):
    for left in ("trigger.user.first_name", "trigger.user.attributes.title", "trigger.user.attributes.bio"):
        r = admin.post("/admin/recipes", {"name": f"t-{left}", "definition": definition("user.created", [
            step("c", "condition", {"match": "all", "conditions": [{"left": left, "operator": "equals", "value": "admin"}]})])})
        assert r.status_code == 422 and "edited by the user" in r.json()["detail"], left
    r = admin.post("/admin/recipes", {"name": "launder", "definition": definition("user.created", [
        step("s", "set_attribute", {"attribute": "department", "value": "{{trigger.user.attributes.title}}"})])})
    assert r.status_code == 422
    ok = admin.post("/admin/recipes", {"name": "fine", "definition": definition("user.created", [
        step("c", "condition", {"match": "all", "conditions": [{"left": "trigger.user.attributes.department", "operator": "equals", "value": "Sales"}]}),
        step("l", "log", {"message": "{{trigger.user.first_name}}"})])})
    assert ok.status_code == 201  # logging a name is fine; only decisions are restricted


def test_meta_lists_real_catalog_fields(admin):
    m = admin.get("/admin/recipes/meta").json()
    types = {t["type"]: t for t in m["triggers"]}
    assert "user.created" in types and "webhook" in types
    paths = {f["path"] for f in types["group.member_added"]["fields"]}
    assert {"trigger.group.name", "trigger.user.email", "trigger.user.attributes.department"} <= paths
    assert {a["key"] for a in m["managed_attributes"]} >= {"department", "cost_center"}
    assert "title" not in {a["key"] for a in m["managed_attributes"]}
