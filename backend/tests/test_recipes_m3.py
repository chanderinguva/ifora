"""R-M3: more triggers, bounded loops over group members, approvals."""

from datetime import timedelta

from sqlalchemy import select

from backend.app.audit.model import AuditEvent
from backend.app.groups.model import user_group_association
from backend.app.recipes import engine
from backend.app.recipes.models import RecipeJob
from backend.app.users.model import User
from tests.conftest import Api, STRONG, make_user
from tests.recipe_helpers import (  # noqa: F401
    T0, definition, jobs, make_recipe, new_group, new_user, rkey, run_worker, step, steps_of,
)

LOG = lambda sid, msg: step(sid, "log", {"message": msg})  # noqa: E731


def members(db, gid):
    db.expire_all()
    return {r[0] for r in db.execute(select(user_group_association.c.user_id).where(user_group_association.c.group_id == gid))}


def add_members(admin, gid, n, prefix="m"):
    ids = []
    for i in range(n):
        u = new_user(admin, f"{prefix}{i}@example.com")
        assert admin.post(f"/admin/groups/{gid}/members", {"user_id": u["id"]}).status_code in (200, 201)
        ids.append(u["id"])
    return ids


# ---- triggers ------------------------------------------------------------------------------------------------

def test_user_deleted_trigger_carries_id_and_email(db, admin):
    rid = make_recipe(admin, definition("user.deleted", [LOG("l", "bye {{trigger.user.email}} #{{trigger.user.id}}")]))
    u = new_user(admin, "gone@example.com")
    assert admin.delete(f"/admin/users/{u['id']}").status_code == 200
    run_worker(T0)
    (j,) = jobs(db, rid)
    assert j.status == "succeeded" and steps_of(db, j.id)[0].output["message"] == f"bye gone@example.com #{u['id']}"


def test_group_created_and_deleted_triggers(db, admin):
    c = make_recipe(admin, definition("group.created", [LOG("l", "new {{trigger.group.name}}")]), name="c")
    d = make_recipe(admin, definition("group.deleted", [LOG("l", "removed {{trigger.group.name}}")]), name="d")
    gid = new_group(admin, "Ops")
    assert admin.delete(f"/admin/groups/{gid}").status_code == 200
    run_worker(T0)
    assert steps_of(db, jobs(db, c)[0].id)[0].output["message"] == "new Ops"
    assert steps_of(db, jobs(db, d)[0].id)[0].output["message"] == "removed Ops"


def test_login_succeeded_trigger(db, admin):
    rid = make_recipe(admin, definition("login.succeeded", [LOG("l", "in {{trigger.user.email}} via {{trigger.login.method}}")]))
    u = make_user(db, "sam@example.com")
    a = Api()
    assert a.login(u.email, STRONG).status_code == 200
    run_worker(T0)
    js = [j for j in jobs(db, rid)]
    assert any(steps_of(db, j.id)[0].output["message"].startswith("in sam@example.com via") for j in js)


def test_attribute_changed_from_to(db, admin):
    cfg = {"attribute": "department", "from_value": "Sales", "to_value": "Support"}
    rid = make_recipe(admin, definition("user.attribute_changed", [LOG("l", "moved")], config=cfg))
    u = new_user(admin, "x@example.com")

    def setdep(v):
        usr = db.get(User, u["id"])
        old = usr.get_profile_attributes()
        usr.set_profile_attributes({**old, "department": v})
        db.commit()
        from backend.app.recipes import events
        events.emit_attribute_changes(db, usr, old, usr.get_profile_attributes())
        db.commit()

    setdep("Sales")           # unset -> Sales: no
    setdep("Support")         # Sales -> Support: yes
    setdep("Sales")           # Support -> Sales: no
    run_worker(T0)
    assert len(jobs(db, rid)) == 1


# ---- loops --------------------------------------------------------------------------------------------------------

def loop_recipe(admin, gid, target, limit=50, extra=None, name="loop"):
    loop = step("each", "for_each_member", {"group_id": gid, "limit": limit}, then=[
        step("tag", "add_to_group", {"group_id": target, "user": "{{loop.user.id}}"}),
        LOG("note", "{{loop.index}}/{{loop.total}} {{loop.user.email}}"),
    ])
    return make_recipe(admin, definition("manual", [loop, *(extra or [])]), name=name)


def test_loop_runs_the_body_for_each_member(db, admin):
    src, dst = new_group(admin, "Source"), new_group(admin, "Target")
    ids = add_members(admin, src, 3)
    rid = loop_recipe(admin, src, dst, extra=[LOG("after", "done {{steps.each.output.processed}} of {{steps.each.output.total}}")])
    assert admin.post(f"/admin/recipes/{rid}/run", {}).status_code == 202
    run_worker()
    (j,) = jobs(db, rid)
    assert j.status == "succeeded", j.error
    assert members(db, dst) == set(ids)
    rows = steps_of(db, j.id)
    assert [r.output["message"] for r in rows if r.step_id == "note"] == [f"{i + 1}/3 m{i}@example.com" for i in range(3)]
    assert rows[-1].output["message"] == "done 3 of 3"


def test_loop_is_bounded_by_limit_and_empty_groups_skip_the_body(db, admin):
    src, dst = new_group(admin, "Source"), new_group(admin, "Target")
    ids = add_members(admin, src, 4)
    rid = loop_recipe(admin, src, dst, limit=2)
    admin.post(f"/admin/recipes/{rid}/run", {})
    run_worker()
    assert members(db, dst) == set(sorted(ids)[:2])
    empty, dst2 = new_group(admin, "Empty"), new_group(admin, "Target2")
    rid2 = loop_recipe(admin, empty, dst2, name="loop2")
    admin.post(f"/admin/recipes/{rid2}/run", {})
    run_worker()
    (j,) = jobs(db, rid2)
    assert j.status == "succeeded" and members(db, dst2) == set() and [r.step_id for r in steps_of(db, j.id)] == ["each"]


def test_loop_validation(admin):
    g = new_group(admin, "G")
    body = [LOG("b", "x")]
    bad = {
        "nested loop": [step("a", "for_each_member", {"group_id": g}, then=[step("b", "for_each_member", {"group_id": g}, then=body)])],
        "loop pills outside a loop": [LOG("x", "{{loop.user.email}}")],
        "tainted loop field for a state change": [step("a", "for_each_member", {"group_id": g}, then=[
            step("b", "set_attribute", {"attribute": "department", "user": "{{loop.user.id}}", "value": "{{loop.user.first_name}}"})])],
        "limit too large": [step("a", "for_each_member", {"group_id": g, "limit": 101}, then=body)],
        "unknown group": [step("a", "for_each_member", {"group_id": 99999}, then=body)],
        "else on a loop": [step("a", "for_each_member", {"group_id": g}, then=body, **{"else": body})],
    }
    for name, steps in bad.items():
        r = admin.post("/admin/recipes", {"name": name, "definition": definition("manual", steps)})
        assert r.status_code == 422, (name, r.text)
    ok = admin.post("/admin/recipes", {"name": "ok", "definition": definition("manual", [step("a", "for_each_member", {"group_id": g}, then=body)])})
    assert ok.status_code == 201, ok.text


def test_loop_iterations_count_toward_the_step_cap(db, admin, monkeypatch):
    from backend.app.config import settings
    monkeypatch.setattr(settings, "RECIPES_MAX_STEPS_PER_JOB", 4)
    src, dst = new_group(admin, "Source"), new_group(admin, "Target")
    add_members(admin, src, 5)
    rid = loop_recipe(admin, src, dst)
    admin.post(f"/admin/recipes/{rid}/run", {})
    run_worker()
    (j,) = jobs(db, rid)
    assert j.status == "failed" and "steps executed" in j.error


# ---- approvals ------------------------------------------------------------------------------------------------------

def approval_recipe(admin, timeout=24):
    return make_recipe(admin, definition("manual", [
        step("ask", "approval", {"message": "Allow the change?", "timeout_hours": timeout},
             then=[LOG("yes", "approved by {{steps.ask.output.decided_by}}")], **{"else": [LOG("no", "refused: {{steps.ask.output.decision}}")]}),
        LOG("end", "finished"),
    ]))


def waiting_job(db, admin, rid):
    admin.post(f"/admin/recipes/{rid}/run", {})
    run_worker()
    (j,) = jobs(db, rid)
    assert j.status == "waiting" and j.approval["decision"] is None
    return j


def test_approval_waits_then_approve_runs_the_then_branch(db, admin):
    rid = approval_recipe(admin)
    j = waiting_job(db, admin, rid)
    assert [(s.step_id, s.status) for s in steps_of(db, j.id)] == [("ask", "waiting")]
    d = admin.get(f"/admin/recipes/jobs/{j.id}").json()
    assert d["status"] == "waiting" and d["approval"]["message"] == "Allow the change?"
    r = admin.post(f"/admin/recipes/jobs/{j.id}/approve")
    assert r.status_code == 200 and r.json()["status"] == "queued"
    run_worker()
    db.expire_all()
    j = db.get(RecipeJob, j.id)
    assert j.status == "succeeded" and j.approval is None
    out = {s.step_id: s.output for s in steps_of(db, j.id)}
    assert out["ask"]["decision"] == "approved" and out["yes"]["message"].startswith("approved by ") and "end" in out and "no" not in out
    assert db.query(AuditEvent).filter(AuditEvent.action == "RECIPE_APPROVAL_DECIDED").count() == 1


def test_deny_runs_the_else_branch(db, admin):
    rid = approval_recipe(admin)
    j = waiting_job(db, admin, rid)
    assert admin.post(f"/admin/recipes/jobs/{j.id}/deny").status_code == 200
    run_worker()
    out = {s.step_id: s.output for s in steps_of(db, j.id)}
    assert out["no"]["message"] == "refused: denied" and "yes" not in out


def test_no_decision_in_time_is_a_timeout_and_takes_the_else_branch(db, admin):
    rid = approval_recipe(admin, timeout=2)
    j = waiting_job(db, admin, rid)
    run_worker(j.approval and engine.utcnow() + timedelta(hours=1))      # not yet
    db.expire_all()
    assert db.get(RecipeJob, j.id).status == "waiting"
    run_worker(engine.utcnow() + timedelta(hours=3))
    db.expire_all()
    out = {s.step_id: s.output for s in steps_of(db, j.id)}
    assert db.get(RecipeJob, j.id).status == "succeeded" and out["no"]["message"] == "refused: timeout"


def test_waiting_time_does_not_count_against_the_runtime_cap(db, admin):
    rid = approval_recipe(admin, timeout=48)
    j = waiting_job(db, admin, rid)
    admin.post(f"/admin/recipes/jobs/{j.id}/approve")
    run_worker(engine.utcnow() + timedelta(hours=20))                    # far beyond the 15 minute cap
    db.expire_all()
    j = db.get(RecipeJob, j.id)
    assert j.status == "succeeded" and j.paused_seconds > 0


def test_decision_rules(db, admin, member):
    rid = approval_recipe(admin)
    j = waiting_job(db, admin, rid)
    assert member.post(f"/admin/recipes/jobs/{j.id}/approve").status_code == 403
    assert admin.post("/admin/recipes/jobs/99999/approve").status_code == 404
    assert admin.post(f"/admin/recipes/jobs/{j.id}/approve").status_code == 200
    assert admin.post(f"/admin/recipes/jobs/{j.id}/deny").status_code == 409           # already decided
    assert admin.post(f"/admin/recipes/jobs/{j.id}/approve").status_code == 409


def test_a_waiting_job_can_be_cancelled(db, admin):
    rid = approval_recipe(admin)
    j = waiting_job(db, admin, rid)
    assert admin.post(f"/admin/recipes/jobs/{j.id}/cancel").json()["status"] == "cancelled"
    run_worker(engine.utcnow() + timedelta(days=3))
    db.expire_all()
    assert db.get(RecipeJob, j.id).status == "cancelled"


def test_dry_run_does_not_wait(db, admin):
    rid = admin.post("/admin/recipes", {"name": "dry", "definition": definition("manual", [
        step("ask", "approval", {"message": "ok?"}, then=[LOG("yes", "y")], **{"else": [LOG("no", "n")]})])}).json()["id"]
    r = admin.post(f"/admin/recipes/{rid}/test", {})
    assert r.json()["status"] == "succeeded" and [s["step_id"] for s in r.json()["steps"]] == ["ask", "yes"]


def test_handlers_cannot_wait_for_approvals(admin):
    d = {**definition("manual", [LOG("a", "x")]), "on_error": [step("h", "approval", {"message": "m"})]}
    assert admin.post("/admin/recipes", {"name": "h", "definition": d}).status_code == 422
