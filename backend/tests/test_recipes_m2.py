"""R-M2: error-handler steps, re-run, cancel, retention, worker heartbeat."""

from datetime import timedelta

import httpx

from backend.app.audit.model import AuditEvent
from backend.app.config import settings
from backend.app.recipes import engine
from backend.app.recipes.models import RecipeJob
from tests.recipe_helpers import (  # noqa: F401
    T0, Remote, definition, install_remote, jobs, make_recipe, new_user, rkey, run_worker, step, steps_of,
)

FAIL = step("call", "http_request", {"method": "GET", "url": "https://svc.example.com/"}, max_attempts=1)


def with_handler(defn, handler):
    return {**defn, "on_error": handler}


# ---- error handler ------------------------------------------------------------------------------------

def test_handler_runs_after_a_failure_and_the_job_still_fails(db, admin, monkeypatch):
    install_remote(monkeypatch, Remote([httpx.Response(404)]))
    d = with_handler(definition("user.created", [FAIL, step("never", "log", {"message": "x"})]),
                     [step("note", "log", {"message": "failed at {{error.step_id}}: {{error.message}}"})])
    rid = make_recipe(admin, d)
    new_user(admin)
    run_worker(T0)
    (j,) = jobs(db, rid)
    assert j.status == "failed" and "call" in j.error and j.in_handler is True
    rows = steps_of(db, j.id)
    assert [(s.step_id, s.status) for s in rows] == [("call", "failed"), ("note", "succeeded")]
    assert "failed at call" in rows[1].output["message"]
    assert db.query(AuditEvent).filter(AuditEvent.action == "RECIPE_JOB_FAILED").count() == 1


def test_handler_does_not_run_on_success(db, admin):
    d = with_handler(definition("user.created", [step("ok", "log", {"message": "fine"})]),
                     [step("note", "log", {"message": "boom"})])
    rid = make_recipe(admin, d)
    new_user(admin)
    run_worker(T0)
    (j,) = jobs(db, rid)
    assert j.status == "succeeded" and j.in_handler is False and [s.step_id for s in steps_of(db, j.id)] == ["ok"]


def test_handler_can_call_out_and_its_own_failure_is_reported(db, admin, monkeypatch):
    remote = Remote([httpx.Response(500)])
    install_remote(monkeypatch, remote)
    d = with_handler(definition("user.created", [FAIL]),
                     [step("alert", "http_request", {"method": "POST", "url": "https://alerts.example.com/h", "body": "{{error.message}}"}, max_attempts=1)])
    rid = make_recipe(admin, d)
    new_user(admin)
    run_worker(T0)
    (j,) = jobs(db, rid)
    assert j.status == "failed" and "error handler step 'alert'" in j.error and len(remote.requests) == 2


def test_handler_validation(admin):
    base = definition("user.created", [step("s1", "log", {"message": "a"})])
    ok = admin.post("/admin/recipes", {"name": "ok", "definition": with_handler(base, [step("h1", "log", {"message": "{{error.message}}"})])})
    assert ok.status_code == 201, ok.text
    bad = {
        "error pills outside the handler": definition("user.created", [step("s1", "log", {"message": "{{error.message}}"})]),
        "main step outputs in the handler": with_handler(base, [step("h1", "log", {"message": "{{steps.s1.output.message}}"})]),
        "duplicate ids across both lists": with_handler(base, [step("s1", "log", {"message": "x"})]),
        "error used for a decision": with_handler(base, [step("h1", "condition", {"match": "all", "conditions": [{"left": "error.message", "operator": "contains", "value": "x"}]})]),
        "error used to change accounts": with_handler(base, [step("h1", "set_attribute", {"attribute": "department", "value": "{{error.message}}"})]),
        "unknown error pill": with_handler(base, [step("h1", "log", {"message": "{{error.secret}}"})]),
    }
    for name, d in bad.items():
        r = admin.post("/admin/recipes", {"name": name, "definition": d})
        assert r.status_code == 422, (name, r.text)


def test_dry_run_runs_the_handler_too(db, admin, monkeypatch):
    install_remote(monkeypatch, Remote([httpx.Response(200)]))
    d = with_handler(definition("manual", [step("s1", "stop", {"outcome": "failed", "message": "no"})]), [step("h1", "log", {"message": "x"})])
    rid = admin.post("/admin/recipes", {"name": "dry", "definition": d}).json()["id"]
    r = admin.post(f"/admin/recipes/{rid}/test", {})
    assert r.status_code == 200 and r.json()["status"] == "failed"   # a deliberate stop does not invoke the handler
    assert [s["step_id"] for s in r.json()["steps"]] == ["s1"]


# ---- re-run -----------------------------------------------------------------------------------------------

def failed_job(db, admin, monkeypatch):
    remote = Remote([httpx.Response(404), httpx.Response(200)])
    install_remote(monkeypatch, remote)
    rid = make_recipe(admin, definition("user.created", [FAIL]))
    new_user(admin)
    run_worker(T0)
    (j,) = jobs(db, rid)
    assert j.status == "failed"
    return rid, j


def test_rerun_creates_a_new_job_from_the_same_version_and_trigger(db, admin, monkeypatch):
    rid, j = failed_job(db, admin, monkeypatch)
    r = admin.post(f"/admin/recipes/jobs/{j.id}/rerun")
    assert r.status_code == 202 and r.json()["rerun_of"] == j.id and r.json()["status"] == "queued"
    run_worker()                                  # the API stamps real time, so run at real time
    old, new = jobs(db, rid)
    assert (old.status, new.status) == ("failed", "succeeded") and new.trigger == old.trigger and new.version == old.version
    assert db.query(AuditEvent).filter(AuditEvent.action == "RECIPE_JOB_RERUN").count() == 1


def test_rerun_rules(db, admin, member, monkeypatch):
    rid, j = failed_job(db, admin, monkeypatch)
    assert member.post(f"/admin/recipes/jobs/{j.id}/rerun").status_code == 403
    assert admin.post("/admin/recipes/jobs/99999/rerun").status_code == 404
    ok = admin.post(f"/admin/recipes/jobs/{j.id}/rerun").json()
    assert admin.post(f"/admin/recipes/jobs/{ok['id']}/rerun").status_code == 409        # queued, not failed
    admin.post(f"/admin/recipes/{rid}/disable")
    assert admin.post(f"/admin/recipes/jobs/{j.id}/rerun").status_code == 409            # recipe disabled


def test_dry_runs_cannot_be_rerun(db, admin):
    rid = admin.post("/admin/recipes", {"name": "d", "definition": definition("manual", [step("s1", "stop", {"outcome": "failed"})])}).json()["id"]
    job = admin.post(f"/admin/recipes/{rid}/test", {}).json()
    assert admin.post(f"/admin/recipes/jobs/{job['id']}/rerun").status_code == 409


# ---- cancel -------------------------------------------------------------------------------------------------

def test_cancel_a_queued_job(db, admin):
    rid = make_recipe(admin, definition("user.created", [step("s1", "log", {"message": "a"})]))
    new_user(admin)
    engine.process_once(T0)                       # dispatch+run happen together, so queue one by hand instead
    admin.post(f"/admin/recipes/{rid}/disable")
    admin.post(f"/admin/recipes/{rid}/enable")
    new_user(admin, "second@example.com")
    from backend.app.tenancy import tenant_session
    s = tenant_session()
    try:
        engine.dispatch_outbox(s, T0 + timedelta(seconds=1))
    finally:
        s.close()
    q = [j for j in jobs(db, rid) if j.status == "queued"]
    assert q
    r = admin.post(f"/admin/recipes/jobs/{q[0].id}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert admin.post(f"/admin/recipes/jobs/{q[0].id}/cancel").status_code == 409          # already finished
    run_worker(T0 + timedelta(seconds=2))
    assert all(j.status != "queued" for j in jobs(db, rid)) and db.query(AuditEvent).filter(AuditEvent.action == "RECIPE_JOB_CANCELLED").count() >= 1


def test_cancel_a_running_job_stops_before_the_next_step(db, admin):
    rid = make_recipe(admin, definition("user.created", [step("s1", "log", {"message": "a"}), step("s2", "log", {"message": "b"})]))
    new_user(admin)
    from backend.app.tenancy import tenant_session
    s = tenant_session()
    try:
        engine.dispatch_outbox(s, T0)
        (jid,) = engine.claim_jobs(s, T0)
    finally:
        s.close()
    assert admin.post(f"/admin/recipes/jobs/{jid}/cancel").json()["cancel_requested"] is True
    run_worker(T0 + timedelta(seconds=1))        # a crashed-and-reclaimed or still-leased job: execute directly
    s = tenant_session()
    try:
        engine.execute_job(s, jid, T0 + timedelta(seconds=2))
    finally:
        s.close()
    db.expire_all()
    j = db.get(RecipeJob, jid)
    assert j.status == "cancelled" and steps_of(db, jid) == []


# ---- retention ---------------------------------------------------------------------------------------------------

def test_old_finished_jobs_and_their_steps_are_pruned(db, admin, monkeypatch):
    rid = make_recipe(admin, definition("user.created", [step("s1", "log", {"message": "a"})]))
    new_user(admin)
    run_worker(T0)
    (j,) = jobs(db, rid)
    jid = j.id
    assert j.status == "succeeded" and len(steps_of(db, jid)) == 1
    monkeypatch.setattr(settings, "RECIPES_JOB_RETENTION_DAYS", 30)
    run_worker(T0 + timedelta(days=29))
    assert len(jobs(db, rid)) == 1
    run_worker(T0 + timedelta(days=31))
    assert jobs(db, rid) == [] and steps_of(db, jid) == []


def test_retention_zero_keeps_everything_and_unfinished_jobs_are_never_pruned(db, admin, monkeypatch):
    rid = make_recipe(admin, definition("user.created", [step("s1", "log", {"message": "a"})]))
    new_user(admin)
    run_worker(T0)
    monkeypatch.setattr(settings, "RECIPES_JOB_RETENTION_DAYS", 0)
    run_worker(T0 + timedelta(days=400))
    assert len(jobs(db, rid)) == 1


# ---- worker heartbeat ---------------------------------------------------------------------------------------------

def test_status_reports_the_worker_heartbeat(admin, tmp_path):
    assert admin.get("/admin/recipes/status").json()["worker_running"] is False
    f = tmp_path / "alive"
    engine.heartbeat(str(f))
    assert f.exists()
    s = admin.get("/admin/recipes/status").json()
    assert s["worker_running"] is True and s["worker_last_seen"]
