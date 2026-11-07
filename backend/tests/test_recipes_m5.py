"""R-M5: owners and role-scoped permissions, DB-enforced version immutability, rate limits, metrics and alerts."""

from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from backend.app.audit.model import AuditEvent
from backend.app.config import settings
from backend.app.recipes import engine
from backend.app.recipes.models import Recipe, RecipeJob, RecipeVersion
from tests.conftest import Api, make_user
from tests.recipe_helpers import (  # noqa: F401
    T0, definition, jobs, make_recipe, new_group, rkey, run_worker, step,
)

LOG = step("l", "log", {"message": "x"})


def other_admin(db, email="two@example.com", super_admin=False):
    u = make_user(db, email, admin=True, super_admin=super_admin)
    a = Api()
    assert a.login(u.email).status_code == 200
    a.user = u
    return a


def manual(admin, name="r", **kw):
    return make_recipe(admin, definition("manual", [LOG]), name=name, **kw)


# ---- owners and permissions ---------------------------------------------------------------------------------------------

def test_creator_owns_the_recipe(db, admin):
    rid = manual(admin, publish=False, enable=False)
    d = admin.get(f"/admin/recipes/{rid}").json()
    assert d["owner"]["id"] == admin.user.id and d["editors"] == [] and d["can_edit"] and d["can_manage"]


def test_other_admins_can_read_but_not_change(db, admin):
    rid = manual(admin)
    two = other_admin(db)
    assert two.get(f"/admin/recipes/{rid}").status_code == 200 and two.get("/admin/recipes").json()["items"][0]["can_edit"] is False
    calls = [
        two.put(f"/admin/recipes/{rid}", {"name": "n", "definition": definition("manual", [LOG])}),
        two.delete(f"/admin/recipes/{rid}"), two.post(f"/admin/recipes/{rid}/publish"), two.post(f"/admin/recipes/{rid}/enable"),
        two.post(f"/admin/recipes/{rid}/disable"), two.post(f"/admin/recipes/{rid}/run", {}), two.post(f"/admin/recipes/{rid}/test", {}),
        two.post(f"/admin/recipes/{rid}/webhook-secret"), two.put(f"/admin/recipes/{rid}/settings", {"owner_id": two.user.id}),
    ]
    assert [c.status_code for c in calls] == [403] * len(calls)
    assert db.get(Recipe, rid).owner_id == admin.user.id


def test_editors_edit_and_dry_run_but_cannot_publish_or_run(db, admin):
    rid = manual(admin)
    two = other_admin(db)
    r = admin.put(f"/admin/recipes/{rid}/settings", {"editors": [two.user.id]})
    assert r.status_code == 200 and r.json()["editors"][0]["id"] == two.user.id
    assert two.put(f"/admin/recipes/{rid}", {"name": "renamed", "definition": definition("manual", [LOG, step("l2", "log", {"message": "y"})])}).status_code == 200
    assert two.post(f"/admin/recipes/{rid}/test", {}).status_code == 200
    for c in (two.post(f"/admin/recipes/{rid}/publish"), two.post(f"/admin/recipes/{rid}/enable"), two.post(f"/admin/recipes/{rid}/run", {}),
              two.delete(f"/admin/recipes/{rid}"), two.put(f"/admin/recipes/{rid}/settings", {"editors": []})):
        assert c.status_code == 403
    assert db.query(AuditEvent).filter(AuditEvent.action == "RECIPE_SETTINGS_CHANGED").count() == 1


def test_job_control_is_owner_only(db, admin):
    rid = manual(admin)
    two = other_admin(db)
    admin.put(f"/admin/recipes/{rid}/settings", {"editors": [two.user.id]})
    admin.post(f"/admin/recipes/{rid}/run", {})
    (j,) = jobs(db, rid)
    assert two.post(f"/admin/recipes/jobs/{j.id}/cancel").status_code == 403
    assert two.post(f"/admin/recipes/jobs/{j.id}/approve").status_code in (403,)
    assert admin.post(f"/admin/recipes/jobs/{j.id}/cancel").status_code == 200
    assert two.post(f"/admin/recipes/jobs/{j.id}/rerun").status_code == 403


def test_super_admin_can_do_everything_and_hand_over_ownership(db, admin):
    rid = manual(admin)
    boss = other_admin(db, "boss@example.com", super_admin=True)
    two = other_admin(db)
    assert boss.post(f"/admin/recipes/{rid}/disable").status_code == 200
    r = boss.put(f"/admin/recipes/{rid}/settings", {"owner_id": two.user.id})
    assert r.status_code == 200 and r.json()["owner"]["id"] == two.user.id
    assert admin.post(f"/admin/recipes/{rid}/enable").status_code == 403       # no longer the owner
    assert two.post(f"/admin/recipes/{rid}/enable").status_code == 200


def test_settings_validation(db, admin, member):
    rid = manual(admin)
    assert admin.put(f"/admin/recipes/{rid}/settings", {"owner_id": member.user.id}).status_code == 422       # not an admin
    assert admin.put(f"/admin/recipes/{rid}/settings", {"editors": [member.user.id]}).status_code == 422
    assert admin.put(f"/admin/recipes/{rid}/settings", {"editors": [999999]}).status_code == 422
    assert admin.put(f"/admin/recipes/{rid}/settings", {"owner_id": 999999}).status_code == 422
    assert admin.put(f"/admin/recipes/{rid}/settings", {"rate_limit_per_hour": -1}).status_code == 422
    two = other_admin(db)
    d = admin.put(f"/admin/recipes/{rid}/settings", {"editors": [two.user.id, two.user.id, admin.user.id]}).json()
    assert [e["id"] for e in d["editors"]] == [two.user.id]                        # de-duplicated, owner dropped
    assert member.put(f"/admin/recipes/{rid}/settings", {"editors": []}).status_code == 403


# ---- immutable versions (database level) ---------------------------------------------------------------------------------

def test_versions_cannot_be_updated_or_deleted_even_with_raw_sql(db, admin):
    rid = manual(admin)
    for stmt in ("UPDATE recipe_versions SET definition = '{}'::jsonb", "DELETE FROM recipe_versions"):
        with pytest.raises(DBAPIError) as e:
            db.execute(text(stmt))
        assert "recipe versions" in str(e.value)
        db.rollback()
    assert db.query(RecipeVersion).filter(RecipeVersion.recipe_id == rid).count() == 1


def test_deleting_the_recipe_still_removes_its_versions(db, admin):
    rid = manual(admin)
    assert admin.delete(f"/admin/recipes/{rid}").status_code == 200
    db.expire_all()
    assert db.query(RecipeVersion).filter(RecipeVersion.recipe_id == rid).count() == 0


# ---- rate limits -----------------------------------------------------------------------------------------------------------

def test_event_triggered_jobs_stop_at_the_hourly_limit(db, admin):
    rid = make_recipe(admin, definition("user.created", [LOG]))
    assert admin.put(f"/admin/recipes/{rid}/settings", {"rate_limit_per_hour": 2}).json()["effective_rate_limit_per_hour"] == 2
    for i in range(4):
        admin.post("/admin/users", {"email": f"u{i}@example.com", "first_name": "A", "last_name": "B", "generate_password": True})
    run_worker()
    assert len(jobs(db, rid)) == 2
    db.expire_all()
    r = db.get(Recipe, rid)
    assert r.throttled_count == 2 and r.last_throttled_at is not None
    assert db.query(AuditEvent).filter(AuditEvent.action == "RECIPE_RATE_LIMITED").count() == 1       # one line per burst
    # the window slides: an hour later there is room again
    admin.post("/admin/users", {"email": "late@example.com", "first_name": "A", "last_name": "B", "generate_password": True})
    run_worker(engine.utcnow() + timedelta(hours=1, minutes=1))
    assert len(jobs(db, rid)) == 3


def test_manual_runs_and_reruns_are_not_throttled(db, admin):
    rid = manual(admin)
    admin.put(f"/admin/recipes/{rid}/settings", {"rate_limit_per_hour": 1})
    for _ in range(3):
        assert admin.post(f"/admin/recipes/{rid}/run", {}).status_code == 202
    assert len(jobs(db, rid)) == 3


def test_server_default_limit_and_clearing(db, admin, monkeypatch):
    monkeypatch.setattr(settings, "RECIPES_DEFAULT_RATE_PER_HOUR", 1)
    rid = make_recipe(admin, definition("user.created", [LOG]))
    assert admin.get(f"/admin/recipes/{rid}").json()["effective_rate_limit_per_hour"] == 1
    admin.put(f"/admin/recipes/{rid}/settings", {"rate_limit_per_hour": 0})                       # explicit 0 = unlimited for this recipe
    for i in range(3):
        admin.post("/admin/users", {"email": f"u{i}@example.com", "first_name": "A", "last_name": "B", "generate_password": True})
    run_worker()
    assert len(jobs(db, rid)) == 3
    assert admin.put(f"/admin/recipes/{rid}/settings", {"clear_rate_limit": True}).json()["rate_limit_per_hour"] is None


# ---- metrics and alerts -------------------------------------------------------------------------------------------------------

def finished_jobs(db, rid, status, n, when=None):
    r = db.get(Recipe, rid)
    now = when or engine.utcnow()
    defn = {"trigger": {"type": "manual", "config": {}, "filter": []}, "steps": []}
    for i in range(n):
        j = engine.create_job(db, r, defn, r.published_version, {}, f"t:{status}:{i}:{now.timestamp()}", now=now, enforce_rate=False)
        j.status, j.started_at, j.finished_at = status, now, now + timedelta(seconds=2)
    db.commit()


def test_metrics_report_rates_durations_and_queue(db, admin):
    rid = manual(admin)
    finished_jobs(db, rid, "succeeded", 3)
    finished_jobs(db, rid, "failed", 1)
    admin.post(f"/admin/recipes/{rid}/run", {})
    m = admin.get("/admin/recipes/metrics?hours=24").json()
    (it,) = m["items"]
    assert it["total"] == 5 and it["by_status"]["failed"] == 1 and it["failure_rate"] == 0.25 and it["p50_seconds"] == 2.0
    assert m["queue"]["queued"] == 1 and m["queue"]["oldest_queued_age_seconds"] is not None
    assert admin.get("/admin/recipes/metrics?hours=0").status_code == 422


def test_failure_rate_alert_fires_once_per_window(db, admin, monkeypatch):
    monkeypatch.setattr(settings, "RECIPES_ALERT_MIN_JOBS", 4)
    rid = manual(admin)
    finished_jobs(db, rid, "failed", 3)
    finished_jobs(db, rid, "succeeded", 3)
    assert engine.check_alerts(db, engine.utcnow(), force=True) == 1
    assert engine.check_alerts(db, engine.utcnow(), force=True) == 0                         # cooldown
    ev = db.query(AuditEvent).filter(AuditEvent.action == "RECIPE_FAILURE_ALERT").one()
    assert ev.event_metadata["failed"] == 3 and ev.event_metadata["finished"] == 6
    assert admin.get("/admin/recipes/metrics").json()["items"][0]["alerting"] is True
    assert engine.check_alerts(db, engine.utcnow() + timedelta(hours=2), force=True) == 0     # old jobs left the window


def test_no_alert_for_healthy_or_tiny_samples(db, admin):
    rid = manual(admin)
    finished_jobs(db, rid, "failed", 2)                                                      # below the minimum job count
    assert engine.check_alerts(db, engine.utcnow(), force=True) == 0
    finished_jobs(db, rid, "succeeded", 20)
    assert engine.check_alerts(db, engine.utcnow(), force=True) == 0
