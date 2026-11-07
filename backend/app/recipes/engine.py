"""Dispatcher and worker (ADR 008 D3). `process_once()` does all currently due work and returns; the CLI loops it.

outbox --dispatch--> job (idempotent) --claim (SKIP LOCKED + lease)--> step by step, one transaction per step.
"""

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.audit.model import AuditAction, AuditEvent
from backend.app.config import settings
from backend.app.recipes import actions, conditions as cond
from backend.app.recipes import templates as tpl
from backend.app.recipes.definition import ACTION_TYPES, compile_program, taint_checker
from backend.app.recipes.models import Recipe, RecipeJob, RecipeJobStep, RecipeOutbox, RecipeVersion
from backend.app.recipes.redact import redact
from backend.app.groups.model import Group, user_group_association
from backend.app.users.model import User
from backend.app.tenancy import Tenant, tenant_session, unscoped

logger = structlog.get_logger(__name__)

BACKOFF_CAP_SECONDS = 300
HEARTBEAT_KEY = "recipes:worker:heartbeat"
HEARTBEAT_STALE_SECONDS = 30


def heartbeat(path: Optional[str] = None) -> None:
    """Tell the world the worker loop is alive: a Redis key (the admin UI shows it) and optionally a file (the compose
    health check reads its mtime, so the check works without Redis or the API)."""
    from backend.app import ratelimit

    try:
        ratelimit._redis().set(HEARTBEAT_KEY, utcnow().isoformat(), ex=120)
    except Exception:  # noqa: BLE001 - a Redis hiccup must not stop the worker
        pass
    if path:
        try:
            with open(path, "w") as f:
                f.write(utcnow().isoformat())
        except OSError:
            pass


def worker_last_seen() -> Optional[datetime]:
    from backend.app import ratelimit

    try:
        v = ratelimit._redis().get(HEARTBEAT_KEY)
        return datetime.fromisoformat(v.decode()) if v else None
    except Exception:  # noqa: BLE001
        return None
OUTBOX_RETENTION_DAYS = 7


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def backoff_seconds(attempt: int) -> int:
    """attempt = number of failures so far (1 = first failure)."""
    return min(settings.RECIPES_RETRY_BASE_SECONDS * (2 ** (attempt - 1)), BACKOFF_CAP_SECONDS)


# ---- trigger context & matching -----------------------------------------------------------------

def event_trigger_ctx(event: RecipeOutbox) -> dict:
    p = event.payload
    actor = p.get("actor") or {"type": "", "id": ""}
    return {
        "event": {"id": event.id, "type": p["type"], "occurred_at": p["occurred_at"]},
        "actor": actor,
        **p.get("data", {}),
    }


def trigger_matches(db: Session, trigger: dict, ctx: dict) -> bool:
    cfg, ttype = trigger.get("config") or {}, trigger["type"]
    if ttype in ("group.member_added", "group.member_removed") and cfg.get("group_id") is not None:
        if ctx.get("group", {}).get("id") != cfg["group_id"]:
            return False
    if ttype == "user.attribute_changed":
        a = ctx.get("attribute", {})
        if a.get("key") != cfg.get("attribute"):
            return False
        for field, want in (("old", cfg.get("from_value")), ("new", cfg.get("to_value"))):
            if want is not None and ("" if a.get(field) is None else str(a.get(field))) != want:
                return False
    if ttype == "login.failed" and ctx.get("login", {}).get("consecutive_failures", 0) < cfg.get("min_failures", 1):
        return False
    flt = trigger.get("filter") or []
    if flt:
        try:
            return cond.evaluate("all", flt, {"trigger": ctx}, taint_checker(db))
        except tpl.TemplateError:
            logger.warning("recipe.filter_error")
            return False
    return True


# ---- job creation ---------------------------------------------------------------------------------

class RateLimited(Exception):
    """The recipe already started its allowed number of jobs this hour."""


def rate_limit_for(recipe: Recipe) -> int:
    return recipe.rate_limit_per_hour if recipe.rate_limit_per_hour is not None else settings.RECIPES_DEFAULT_RATE_PER_HOUR


def _check_rate(db: Session, recipe: Recipe, now: datetime) -> None:
    limit = rate_limit_for(recipe)
    if limit <= 0:
        return
    started = db.query(func.count(RecipeJob.id)).filter(
        RecipeJob.recipe_id == recipe.id, RecipeJob.mode == "live", RecipeJob.created_at > now - timedelta(hours=1)).scalar()
    if started < limit:
        return
    first = recipe.last_throttled_at is None or recipe.last_throttled_at < now - timedelta(minutes=10)
    recipe.throttled_count, recipe.last_throttled_at = (recipe.throttled_count or 0) + 1, now
    if first:  # one audit line per burst, not one per dropped event
        db.add(AuditEvent(action=AuditAction.RECIPE_RATE_LIMITED, actor_id=f"recipe:{recipe.id}", actor_type="recipe",
                          target_id=str(recipe.id), target_type="recipe", metadata={"limit_per_hour": limit}))
        logger.warning("recipe.rate_limited", recipe_id=recipe.id, limit_per_hour=limit)
    raise RateLimited()


def create_job(
    db: Session, recipe: Recipe, definition: dict, version: Optional[int], trigger: dict, key: str,
    *, depth: int = 0, mode: str = "live", event_id: Optional[int] = None, now: Optional[datetime] = None,
    enforce_rate: bool = True,
) -> Optional[RecipeJob]:
    """Insert a job; returns None when the idempotency key already exists (duplicate delivery).
    Raises RateLimited for automatic triggers over the recipe's hourly limit (explicit admin actions pass enforce_rate=False)."""
    now = now or utcnow()
    if mode == "live" and enforce_rate:
        _check_rate(db, recipe, now)
    job = RecipeJob(
        recipe_id=recipe.id, version=version, mode=mode, status="queued" if mode == "live" else "running",
        definition=definition, trigger=trigger, trigger_type=definition["trigger"]["type"], event_id=event_id,
        idempotency_key=key, depth=depth, step_outputs={}, next_run_at=now, created_at=now,
        locked_until=now + timedelta(days=1) if mode != "live" else None,
        started_at=now if mode != "live" else None,
    )
    try:
        with db.begin_nested():
            db.add(job)
            db.flush()
    except IntegrityError:
        return None
    return job


def _published(db: Session, recipe: Recipe, cache: dict) -> Optional[dict]:
    k = (recipe.id, recipe.published_version)
    if k not in cache:
        v = db.query(RecipeVersion).filter(
            RecipeVersion.recipe_id == recipe.id, RecipeVersion.version == recipe.published_version
        ).first()
        cache[k] = v.definition if v else None
    return cache[k]


# ---- dispatcher -----------------------------------------------------------------------------------------

def dispatch_outbox(db: Session, now: datetime, batch: int = 100) -> Dict[str, int]:
    stats = {"events": 0, "jobs": 0}
    rows = (
        db.query(RecipeOutbox).filter(RecipeOutbox.dispatched_at.is_(None))
        .order_by(RecipeOutbox.id).with_for_update(skip_locked=True).limit(batch).all()
    )
    cache: dict = {}
    for ev in rows:
        stats["events"] += 1
        if ev.depth <= settings.RECIPES_MAX_EVENT_DEPTH:
            ctx = event_trigger_ctx(ev)
            recipes = db.query(Recipe).filter(
                Recipe.enabled.is_(True), Recipe.published_trigger_type == ev.event_type
            ).order_by(Recipe.id).all()
            for r in recipes:
                if ev.origin_recipe_id == r.id:  # a recipe never receives the events it caused itself
                    continue
                definition = _published(db, r, cache)
                if definition is None or not trigger_matches(db, definition["trigger"], ctx):
                    continue
                try:
                    if create_job(db, r, definition, r.published_version, ctx, f"evt:{ev.id}",
                                  depth=ev.depth, event_id=ev.id, now=now):
                        stats["jobs"] += 1
                except RateLimited:
                    stats["throttled"] = stats.get("throttled", 0) + 1
        ev.dispatched_at = now
    db.commit()
    return stats


def schedule_due(db: Session, now: datetime) -> int:
    created = 0
    cache: dict = {}
    for r in db.query(Recipe).filter(Recipe.enabled.is_(True), Recipe.published_trigger_type == "schedule").all():
        definition = _published(db, r, cache)
        if not definition:
            continue
        interval = definition["trigger"]["config"]["interval_minutes"] * 60
        slot = int(now.timestamp() // interval)
        key = f"sched:{slot}"
        if db.query(RecipeJob.id).filter(RecipeJob.recipe_id == r.id, RecipeJob.idempotency_key == key).first():
            continue
        when = datetime.fromtimestamp(slot * interval, timezone.utc).isoformat()
        trig = {"event": {"id": 0, "type": "schedule", "occurred_at": now.isoformat()},
                "actor": {"type": "", "id": ""}, "schedule": {"scheduled_for": when}}
        try:
            if create_job(db, r, definition, r.published_version, trig, key, now=now):
                created += 1
        except RateLimited:
            pass
    db.commit()
    return created


# ---- execution ----------------------------------------------------------------------------------------------

def _audit_job(db: Session, job: RecipeJob, action: AuditAction, extra: Optional[dict] = None) -> None:
    meta = {"recipe_id": job.recipe_id, "job_id": job.id, "version": job.version, "trigger": job.trigger_type}
    meta.update(extra or {})
    db.add(AuditEvent(action=action, actor_id=f"recipe:{job.recipe_id}", actor_type="recipe",
                      target_id=str(job.recipe_id), target_type="recipe", metadata=meta))


def _finish(db: Session, job: RecipeJob, status: str, now: datetime, error: Optional[str] = None) -> None:
    job.status, job.finished_at, job.locked_until = status, now, None
    job.error = (error or None) and error[:500]
    if job.mode == "live":
        action = {"succeeded": AuditAction.RECIPE_JOB_SUCCEEDED, "failed": AuditAction.RECIPE_JOB_FAILED,
                  "cancelled": AuditAction.RECIPE_JOB_CANCELLED}[status]
        _audit_job(db, job, action, {"error": job.error} if job.error else None)
    db.commit()


def _end(db: Session, job: RecipeJob, status: str, now: datetime, error: Optional[str] = None) -> str:
    """Finish at the natural end of the main steps or of the error handler. A job whose handler ran has still failed."""
    if job.in_handler:
        status, error = "failed", job.error or error
    _finish(db, job, status, now, error)
    return status


def _loop_ctx(db: Session, job: RecipeJob) -> dict:
    loops = (job.step_outputs or {}).get("_loops") or {}
    active = loops.get("active")
    if not active:
        return {}
    from backend.app.recipes.events import user_snapshot

    st = loops[active]
    user = db.get(User, st["members"][st["index"]])
    return {"index": st["index"] + 1, "total": st["total"], "user": user_snapshot(user) if user else {}}


def _step_row(job: RecipeJob, seq: int, instr: dict, status: str, attempt: int, inp, out, err, started, finished):
    return RecipeJobStep(
        job_id=job.id, seq=seq, step_id=instr["id"], type=instr["type"], status=status, attempt=attempt,
        input=redact(inp) if inp is not None else None, output=redact(out) if out is not None else None,
        error=(err or None) and err[:500], started_at=started, finished_at=finished,
    )


def execute_job(db: Session, job_id: int, now: datetime) -> str:
    """Run a claimed (`running`) job until it finishes or must wait for a retry. Returns the resulting status."""
    taint = taint_checker(db)
    while True:
        job = db.get(RecipeJob, job_id)
        if job is None or job.status != "running":
            return job.status if job else "missing"
        recipe = db.get(Recipe, job.recipe_id)
        if job.cancel_requested:
            _finish(db, job, "cancelled", now, "cancelled by an administrator")
            return "cancelled"
        if job.mode == "live" and (recipe is None or not recipe.enabled):
            _finish(db, job, "cancelled", now, "recipe disabled or deleted")
            return "cancelled"
        if job.executed_steps >= settings.RECIPES_MAX_STEPS_PER_JOB:
            _finish(db, job, "failed", now, f"stopped: more than {settings.RECIPES_MAX_STEPS_PER_JOB} steps executed")
            return "failed"
        paused = job.paused_seconds or 0
        if job.approval:  # resuming from a wait that is not credited yet (done when the step completes)
            paused += max(int((now - datetime.fromisoformat(job.approval["requested_at"])).total_seconds()), 0)
        if (now - job.created_at).total_seconds() - paused > settings.RECIPES_MAX_RUNTIME_SECONDS:
            _finish(db, job, "failed", now, "stopped: maximum runtime exceeded")
            return "failed"
        program = compile_program(job.definition.get("on_error", []) if job.in_handler else job.definition["steps"])
        while job.pc < len(program) and program[job.pc]["type"] in ("jump", "loop_next"):
            ins = program[job.pc]
            if ins["type"] == "jump":
                job.pc = ins["to"]
                continue
            loops = dict((job.step_outputs or {}).get("_loops") or {})  # loop_next: next member, or leave the loop
            lid = program[ins["loop_pc"]]["id"]
            st = dict(loops[lid])
            st["index"] += 1
            loops[lid] = st
            if st["index"] < st["total"]:
                job.pc = ins["loop_pc"] + 1
            else:
                loops["active"], job.pc = None, job.pc + 1
            outputs = dict(job.step_outputs or {})
            outputs["_loops"] = loops
            outputs[lid] = {"total": st["total"], "processed": min(st["index"], st["total"])}
            job.step_outputs = outputs
        if job.pc >= len(program):
            return _end(db, job, "succeeded", now)
        instr = program[job.pc]
        seq = job.executed_steps + 1
        attempt = job.attempt + 1
        data = {
            "trigger": job.trigger,
            "steps": {k: {"output": v} for k, v in (job.step_outputs or {}).items()},
            "recipe": {"id": job.recipe_id, "name": recipe.name if recipe else "", "version": job.version or 0},
            "job": {"id": job.id},
            "error": (job.step_outputs or {}).get("_error", {}),
            "loop": _loop_ctx(db, job),
        }
        rc = actions.RunCtx(db, job.recipe_id, job.id, instr["id"], data, job.mode == "dry_run", taint)
        db.info["recipe_origin"] = {"recipe_id": job.recipe_id, "job_id": job.id, "depth": job.depth}
        inp = out = None
        extra: Dict[str, Any] = {}
        waiting = False
        decided_approval = False
        err: Optional[actions.StepError] = None
        stop: Optional[tuple] = None
        next_pc = job.pc + 1
        try:
            with db.begin_nested():
                if instr["type"] == "condition":
                    c = instr["config"]
                    try:
                        result = cond.evaluate(c["match"], c["conditions"], data, taint)
                    except tpl.TemplateError as e:
                        raise actions.StepError(str(e))
                    inp, out = {"conditions": c["conditions"], "match": c["match"]}, {"result": result}
                    next_pc = instr["true_to"] if result else instr["false_to"]
                elif instr["type"] == "for_each_member":
                    c = instr["config"]
                    if db.get(Group, c["group_id"]) is None:
                        raise actions.StepError("the group no longer exists")
                    ids = [r[0] for r in db.execute(
                        select(user_group_association.c.user_id).where(user_group_association.c.group_id == c["group_id"])
                        .order_by(user_group_association.c.user_id).limit(c["limit"]))]
                    loops = dict((job.step_outputs or {}).get("_loops") or {})
                    loops[instr["id"]] = {"members": ids, "index": 0, "total": len(ids)}
                    loops["active"] = instr["id"] if ids else None
                    extra["_loops"] = loops
                    inp, out = {"group_id": c["group_id"], "limit": c["limit"]}, {"total": len(ids), "processed": 0}
                    next_pc = job.pc + 1 if ids else instr["end_to"]
                elif instr["type"] == "approval":
                    ap = job.approval if (job.approval or {}).get("step_id") == instr["id"] else None
                    if ap is None and job.mode == "dry_run":
                        inp, out = {"message": rc.render(instr["config"]["message"], tainted_ok=True)}, {"decision": "approved", "decided_by": "dry run"}
                        next_pc = instr["true_to"]
                    elif ap is None:
                        msg = str(rc.render(instr["config"]["message"], tainted_ok=True))[:500]
                        expires = now + timedelta(hours=instr["config"]["timeout_hours"])
                        job.approval = {"step_id": instr["id"], "message": msg, "requested_at": now.isoformat(),
                                        "expires_at": expires.isoformat(), "decision": None, "decided_by": None}
                        job.status, job.locked_until, job.next_run_at = "waiting", None, expires
                        inp, waiting = {"message": msg, "expires_at": expires.isoformat()}, True
                    else:
                        decision = ap.get("decision")
                        if decision is None and now >= datetime.fromisoformat(ap["expires_at"]):
                            decision = "timeout"
                        inp, out = {"message": ap["message"]}, {"decision": decision, "decided_by": ap.get("decided_by") or ""}
                        next_pc = instr["true_to"] if decision == "approved" else instr["false_to"]
                        decided_approval = True
                elif instr["type"] == "stop":
                    msg = rc.render(instr["config"].get("message", ""), tainted_ok=True)
                    inp, out = {"outcome": instr["config"]["outcome"], "message": msg}, {}
                    stop = (instr["config"]["outcome"], str(msg))
                else:
                    inp, out = actions.EXECUTORS[instr["type"]](rc, instr["config"])
        except actions.StepError as e:
            err = e
        except Exception as e:  # noqa: BLE001 - unexpected bug or DB hiccup: retryable, details only in logs
            logger.error("recipe.step_crashed", recipe_id=job.recipe_id, job_id=job.id, step=instr["id"], error=type(e).__name__)
            err = actions.StepError("internal error", retryable=True)
        finally:
            db.info.pop("recipe_origin", None)
        job = db.get(RecipeJob, job_id)
        started = now
        if err is None and waiting:
            db.add(_step_row(job, seq, instr, "waiting", attempt, inp, None, None, started, None))
            job.executed_steps = seq
            db.commit()
            return "waiting"
        if err is None:
            outputs = dict(job.step_outputs or {})
            outputs.update(extra)
            outputs[instr["id"]] = out
            if decided_approval:
                waited = int((now - datetime.fromisoformat(job.approval["requested_at"])).total_seconds())
                job.paused_seconds = (job.paused_seconds or 0) + max(waited, 0)
                job.approval = None
            job.step_outputs = outputs
            job.executed_steps, job.attempt, job.pc = seq, 0, next_pc
            job.locked_until = now + timedelta(seconds=settings.RECIPES_LEASE_SECONDS) if job.mode == "live" else job.locked_until
            db.add(_step_row(job, seq, instr, "succeeded", attempt, inp, out, None, started, now))
            if stop is not None:
                return _end(db, job, "succeeded" if stop[0] == "success" else "failed", now,
                            None if stop[0] == "success" else (stop[1] or "stopped by a stop step"))
            db.commit()
            continue
        # failure ---------------------------------------------------------------------------------
        max_attempts = instr.get("max_attempts", 1) if instr["type"] in ACTION_TYPES else 1
        if err.retryable and attempt < max_attempts and job.mode == "live":
            db.add(_step_row(job, seq, instr, "retrying", attempt, inp, None, err.message, started, now))
            job.attempt = attempt
            job.status, job.locked_until = "queued", None
            job.next_run_at = now + timedelta(seconds=backoff_seconds(attempt))
            db.commit()
            return "queued"
        db.add(_step_row(job, seq, instr, "failed", attempt, inp, None, err.message, started, now))
        if instr.get("on_error") == "continue" and instr["type"] in ACTION_TYPES:
            outputs = dict(job.step_outputs or {})
            outputs[instr["id"]] = {"error": err.message}
            job.step_outputs = outputs
            job.executed_steps, job.attempt, job.pc = seq, 0, job.pc + 1
            db.commit()
            continue
        job.executed_steps = seq
        msg = f"step '{instr['id']}': {err.message}"
        if job.in_handler:
            _finish(db, job, "failed", now, f"{job.error or ''} | error handler {msg}")
            return "failed"
        if job.definition.get("on_error") and job.mode in ("live", "dry_run"):
            # the Monitor / On-error idea (ADR 008 R-M2): run the handler steps, then the job still ends as failed
            job.error = msg[:500]
            job.in_handler, job.pc, job.attempt = True, 0, 0
            outputs = dict(job.step_outputs or {})
            outputs["_error"] = {"message": err.message, "step_id": instr["id"]}
            job.step_outputs = outputs
            db.commit()
            continue
        _finish(db, job, "failed", now, msg)
        return "failed"


def run_dry(db: Session, recipe: Recipe, definition: dict, trigger: dict, now: Optional[datetime] = None) -> RecipeJob:
    """Synchronously execute the draft without side effects. The job is stored so the history view can show it."""
    now = now or utcnow()
    key = f"dry:{int(now.timestamp() * 1000)}:{recipe.id}"
    job = create_job(db, recipe, definition, None, trigger, key, mode="dry_run", now=now)
    if job is None:  # same-millisecond double click
        key += "x"
        job = create_job(db, recipe, definition, None, trigger, key, mode="dry_run", now=now)
    db.commit()
    execute_job(db, job.id, now)
    return db.get(RecipeJob, job.id)


# ---- worker -------------------------------------------------------------------------------------------------

def claim_jobs(db: Session, now: datetime) -> List[int]:
    rows = (
        db.query(RecipeJob)
        .filter(
            RecipeJob.mode == "live",
            or_(
                and_(RecipeJob.status.in_(("queued", "waiting")), RecipeJob.next_run_at <= now),
                and_(RecipeJob.status == "running", RecipeJob.locked_until < now),
            ),
        )
        .order_by(RecipeJob.next_run_at, RecipeJob.id)
        .with_for_update(skip_locked=True)
        .limit(settings.RECIPES_WORKER_BATCH)
        .all()
    )
    running: Dict[int, int] = {}
    ids = []
    for j in rows:
        n = running.get(j.recipe_id)
        if n is None:
            n = db.query(RecipeJob).filter(
                RecipeJob.recipe_id == j.recipe_id, RecipeJob.status == "running", RecipeJob.locked_until >= now
            ).count()
        if n >= settings.RECIPES_MAX_CONCURRENT_PER_RECIPE:
            running[j.recipe_id] = n
            continue
        running[j.recipe_id] = n + 1
        j.status = "running"
        j.locked_until = now + timedelta(seconds=settings.RECIPES_LEASE_SECONDS)
        j.started_at = j.started_at or now
        ids.append(j.id)
    db.commit()
    return ids


def prune_jobs(db: Session, now: datetime) -> int:
    """Delete finished jobs (and, by cascade, their step history) older than RECIPES_JOB_RETENTION_DAYS. 0 keeps everything."""
    days = settings.RECIPES_JOB_RETENTION_DAYS
    if days <= 0:
        return 0
    n = db.query(RecipeJob).filter(
        RecipeJob.status.in_(("succeeded", "failed", "cancelled")), RecipeJob.finished_at < now - timedelta(days=days)
    ).delete(synchronize_session=False)
    db.commit()
    return n


_alert_gate: Dict[object, float] = {}


def check_alerts(db: Session, now: datetime, force: bool = False) -> int:
    """Raise an alert (audit event + warning log) for each enabled recipe whose recent failure rate is too high.
    At most one alert per recipe per window; evaluated at most every 30 s per tenant by the worker."""
    gate_key = db.info.get("tenant_id")
    if not force:
        mono = time.monotonic()
        if mono - _alert_gate.get(gate_key, -1e9) < 30:
            return 0
        _alert_gate[gate_key] = mono
    window = timedelta(minutes=settings.RECIPES_ALERT_WINDOW_MINUTES)
    rows = (
        db.query(RecipeJob.recipe_id, RecipeJob.status, func.count(RecipeJob.id))
        .filter(RecipeJob.mode == "live", RecipeJob.status.in_(("succeeded", "failed")), RecipeJob.finished_at > now - window)
        .group_by(RecipeJob.recipe_id, RecipeJob.status).all()
    )
    counts: Dict[int, Dict[str, int]] = {}
    for rid, st, n in rows:
        counts.setdefault(rid, {})[st] = n
    raised = 0
    for rid, c in counts.items():
        failed, total = c.get("failed", 0), c.get("failed", 0) + c.get("succeeded", 0)
        if total < settings.RECIPES_ALERT_MIN_JOBS or failed / total < settings.RECIPES_ALERT_FAILURE_RATE:
            continue
        r = db.get(Recipe, rid)
        if r is None or not r.enabled or (r.last_alert_at and r.last_alert_at > now - window):
            continue
        r.last_alert_at = now
        db.add(AuditEvent(action=AuditAction.RECIPE_FAILURE_ALERT, actor_id=f"recipe:{r.id}", actor_type="recipe",
                          target_id=str(r.id), target_type="recipe",
                          metadata={"failed": failed, "finished": total, "window_minutes": settings.RECIPES_ALERT_WINDOW_MINUTES}))
        logger.warning("recipe.failure_alert", recipe_id=r.id, failed=failed, finished=total)
        raised += 1
    db.commit()
    return raised


def process_tenant(db: Session, now: datetime) -> Dict[str, int]:
    stats = dispatch_outbox(db, now)
    stats["scheduled"] = schedule_due(db, now)
    ids = claim_jobs(db, now)
    stats["ran"] = 0
    for jid in ids:
        execute_job(db, jid, now)
        stats["ran"] += 1
    prune_jobs(db, now)
    check_alerts(db, now)
    db.query(RecipeOutbox).filter(
        RecipeOutbox.dispatched_at.is_not(None), RecipeOutbox.dispatched_at < now - timedelta(days=OUTBOX_RETENTION_DAYS)
    ).delete(synchronize_session=False)
    db.commit()
    return stats


def process_once(now: Optional[datetime] = None) -> Dict[str, int]:
    """Process all currently due work for every tenant. Safe to run from several workers at once."""
    now = now or utcnow()
    total = {"events": 0, "jobs": 0, "scheduled": 0, "ran": 0}
    if not settings.RECIPES_ENABLED:
        return total
    from backend.app.db import SessionLocal

    s = SessionLocal()
    try:
        with unscoped(s):
            tenant_ids = [t.id for t in s.query(Tenant).filter(Tenant.status == "active").all()]
    finally:
        s.close()
    for tid in tenant_ids:
        db = tenant_session(tid)
        try:
            for k, v in process_tenant(db, now).items():
                total[k] = total.get(k, 0) + v
        except Exception:  # noqa: BLE001 - one tenant must not stop the others
            db.rollback()
            logger.exception("recipe.tenant_failed", tenant_id=tid)
        finally:
            db.close()
    return total
