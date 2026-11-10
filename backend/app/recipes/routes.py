"""Admin API for recipes, connections and job history, plus the signed inbound webhook (ADR 008)."""

import hashlib
import hmac
import json
import re
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app import ratelimit
from backend.app.audit.model import AuditAction, AuditEvent
from backend.app.audit.service import record
from backend.app.auth.deps import require_admin
from backend.app.config import settings
from backend.app.db import get_db
from backend.app.groups.model import Group
from backend.app.listing import ListParams, list_params, paginate, sortable
from backend.app.scim import filter as flt
from backend.app.profiles import catalog as profile_catalog
from backend.app.recipes import calls
from backend.app.recipes import conditions as cond
from backend.app.recipes import crypto, definition as defn, engine, formula, portable
from backend.app.recipes import templates as tpl
from backend.app.recipes.models import (
    LookupTable, Recipe, RecipeConnection, RecipeJob, RecipeJobStep, RecipeVersion,
)
from backend.app.recipes.redact import redact
from backend.app.users.model import User


def _enabled():
    if not settings.RECIPES_ENABLED:
        raise HTTPException(status_code=404, detail="Recipes are not enabled")


router = APIRouter(prefix="/admin/recipes", tags=["recipes"], dependencies=[Depends(_enabled)])

JOB_LIST_ATTRS = {
    "status": flt.Attr("str", RecipeJob.status), "created_at": flt.Attr("date", RecipeJob.created_at),
    "started_at": flt.Attr("date", RecipeJob.started_at), "finished_at": flt.Attr("date", RecipeJob.finished_at),
}
JOB_SORT = sortable(JOB_LIST_ATTRS, id=RecipeJob.id)
connections_router = APIRouter(prefix="/admin/recipe-connections", tags=["recipes"], dependencies=[Depends(_enabled)])
hooks_router = APIRouter(prefix="/hooks/recipes", tags=["recipes"])

NOW = lambda: datetime.now(timezone.utc)  # noqa: E731


# ---- serialisation ---------------------------------------------------------------------------------

def _people(db: Session, ids: list) -> list:
    users = {u.id: u for u in db.query(User).filter(User.id.in_([i for i in ids if i is not None])).all()} if ids else {}
    return [{"id": i, "email": users[i].email} for i in ids if i in users]


def _recipe_dict(db: Session, r: Recipe, detail: bool = False, viewer: Optional[User] = None) -> dict:
    published = None
    if r.published_version is not None:
        v = db.query(RecipeVersion).filter(RecipeVersion.recipe_id == r.id, RecipeVersion.version == r.published_version).first()
        published = v.definition if v else None
    last = db.query(RecipeJob).filter(RecipeJob.recipe_id == r.id, RecipeJob.mode == "live").order_by(RecipeJob.id.desc()).first()
    d = {
        "id": r.id,
        "name": r.name,
        "description": r.description,
        "enabled": r.enabled,
        "trigger_type": r.draft["trigger"]["type"],
        "published_version": r.published_version,
        "published_trigger_type": r.published_trigger_type,
        "has_unpublished_changes": published != r.draft,
        "webhook_path": f"/api/v1/hooks/recipes/{r.public_id}" if "webhook" in (r.draft["trigger"]["type"], r.published_trigger_type) else None,
        "webhook_secret_set": r.webhook_secret_enc is not None,
        "last_job": {"id": last.id, "status": last.status, "created_at": last.created_at.isoformat()} if last else None,
        "created_at": r.created_at.isoformat(),
        "updated_at": r.updated_at.isoformat(),
        "owner": (_people(db, [r.owner_id]) or [None])[0],
        "editors": _people(db, list(r.editors or [])),
        "rate_limit_per_hour": r.rate_limit_per_hour,
        "effective_rate_limit_per_hour": engine.rate_limit_for(r),
        "throttled_count": r.throttled_count or 0,
        "last_throttled_at": r.last_throttled_at.isoformat() if r.last_throttled_at else None,
        "last_alert_at": r.last_alert_at.isoformat() if r.last_alert_at else None,
        "can_edit": can_edit(viewer, r) if viewer else None,
        "can_manage": can_manage(viewer, r) if viewer else None,
    }
    if detail:
        d["draft"] = r.draft
    return d


def _job_dict(j: RecipeJob, name: Optional[str] = None) -> dict:
    return {
        "id": j.id, "recipe_id": j.recipe_id, "recipe_name": name, "version": j.version, "mode": j.mode,
        "status": j.status, "trigger_type": j.trigger_type, "depth": j.depth, "executed_steps": j.executed_steps,
        "attempt": j.attempt, "error": j.error, "in_handler": j.in_handler, "approval": ({k: v for k, v in (j.approval or {}).items() if k != "decided_by"} or None), "cancel_requested": j.cancel_requested,
        "rerun_of": j.rerun_of,
        "created_at": j.created_at.isoformat(),
        "started_at": j.started_at.isoformat() if j.started_at else None,
        "finished_at": j.finished_at.isoformat() if j.finished_at else None,
        "next_run_at": j.next_run_at.isoformat() if j.next_run_at else None,
    }


def _job_detail(db: Session, j: RecipeJob) -> dict:
    r = db.get(Recipe, j.recipe_id)
    steps = db.query(RecipeJobStep).filter(RecipeJobStep.job_id == j.id).order_by(RecipeJobStep.id).all()
    names = {}

    def collect(items):
        for s in items:
            names[s["id"]] = s.get("name")
            collect(s.get("then", []))
            collect(s.get("else", []))

    collect(j.definition.get("steps", []))
    collect(j.definition.get("on_error", []))
    return {
        **_job_dict(j, r.name if r else None),
        "trigger": redact(j.trigger),
        "steps": [
            {
                "seq": s.seq, "step_id": s.step_id, "name": names.get(s.step_id), "type": s.type, "status": s.status,
                "attempt": s.attempt, "input": redact(s.input), "output": redact(s.output), "error": s.error,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "finished_at": s.finished_at.isoformat() if s.finished_at else None,
            }
            for s in steps
        ],
    }


def _get(db: Session, rid: int) -> Recipe:
    r = db.get(Recipe, rid)
    if r is None:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return r


def can_edit(user: User, r: Recipe) -> bool:
    """Draft editing and dry runs: the owner, listed editors and super admins."""
    return bool(user.is_super_admin or user.id == r.owner_id or user.id in (r.editors or []))


def can_manage(user: User, r: Recipe) -> bool:
    """Publish, enable, run, delete, job control, access settings: the owner and super admins. Editors cannot."""
    return bool(user.is_super_admin or user.id == r.owner_id)


def _need(db: Session, rid: int, actor: User, level: str) -> Recipe:
    r = _get(db, rid)
    if not (can_manage if level == "manage" else can_edit)(actor, r):
        raise HTTPException(status_code=403, detail="Only the owner of this recipe can do that" if level == "manage" else "You do not have edit access to this recipe")
    return r


def _validated(db: Session, definition: Any, for_publish: bool = False, actor: Optional[User] = None) -> dict:
    try:
        return defn.validate_definition(db, definition, for_publish=for_publish, actor=actor)
    except defn.DefinitionError as e:
        raise HTTPException(status_code=422, detail=str(e))


def _audit(db, action, actor, r_id, meta=None, request=None):
    record(db, action, request, actor, r_id, "recipe", meta)


# ---- status / meta ----------------------------------------------------------------------------------

@router.get("/status")
def status(_: User = Depends(require_admin)):
    ok = crypto.available()
    seen = engine.worker_last_seen()
    return {"enabled": True, "email_available": bool(settings.SMTP_HOST and settings.SMTP_FROM), "connections_available": ok, "webhooks_available": ok,
            "egress_restricted": bool(settings.RECIPES_HTTP_ALLOWED_HOSTS.strip()),
            "worker_last_seen": seen.isoformat() if seen else None,
            "worker_running": bool(seen and (NOW() - seen).total_seconds() < engine.HEARTBEAT_STALE_SECONDS)}


TRIGGER_INFO = {
    "user.created": ("A user is created", "Fires after an administrator creates a user."),
    "user.activated": ("A user is activated", "Fires when an inactive account is activated."),
    "user.deactivated": ("A user is deactivated", "Fires when an account is deactivated."),
    "user.updated": ("A user is updated", "Fires when an administrator edits a user."),
    "user.attribute_changed": ("An attribute changes", "Fires when one administrator-managed profile attribute changes."),
    "group.member_added": ("A member is added to a group", "Optionally limited to one group."),
    "group.member_removed": ("A member is removed from a group", "Optionally limited to one group."),
    "login.failed": ("A sign-in fails", "Fires on a wrong password; set a minimum number of consecutive failures."),
    "user.deleted": ("A user is deleted", "Fires after an administrator deletes a user; only id and email are available."),
    "group.created": ("A group is created", "Fires when an administrator creates a group."),
    "group.deleted": ("A group is deleted", "Fires when an administrator deletes a group."),
    "login.succeeded": ("A sign-in succeeds", "Fires after a completed sign-in (password and any second factor)."),
    "session.logout": ("A user signs out", "Fires when a user ends their own session."),
    "mfa.enabled": ("Multi-factor is turned on", "Fires when a user enables an authenticator app."),
    "mfa.disabled": ("Multi-factor is turned off", "Fires when a user disables their authenticator app."),
    "password.changed": ("A password changes", "Fires on a self-service change, an administrator reset, or a completed reset or invitation link."),
    "schedule": ("On a schedule", "Runs every N minutes (5 to 1440)."),
    "manual": ("Run manually", "Started by an administrator with the Run button."),
    "webhook": ("An external system calls a webhook", "Signed with a per-recipe secret (HMAC-SHA256)."),
    "call": ("Called by another recipe", "Runs when a Call recipe step in another recipe uses it; it declares inputs and outputs."),
}
STEP_INFO = {
    "add_to_group": ("Add user to group", "action"), "remove_from_group": ("Remove user from group", "action"),
    "set_attribute": ("Set a profile attribute", "action"), "activate_user": ("Activate user", "action"),
    "deactivate_user": ("Deactivate user", "action"), "http_request": ("Send an HTTP request", "action"),
    "log": ("Write to the job log", "action"),
    "connector_action": ("Run a connector action", "action"),
    "send_slack": ("Send a Slack message", "action"), "send_email": ("Send an email", "action"), "condition": ("If / else", "control"), "stop": ("Stop", "control"), "handle_errors": ("Handle errors", "control"),
    "for_each_member": ("For each member of a group", "control"), "for_each_item": ("For each item in a list", "control"), "approval": ("Wait for approval", "control"),
    "lookup_row": ("Look up a row", "action"), "lookup_write": ("Add, update or delete a lookup row", "action"),
    "set_variable": ("Set a variable", "control"), "wait": ("Wait (delay)", "control"), "throttle": ("Throttle", "control"),
    "call_recipe": ("Call a recipe", "control"), "return_data": ("Return data to the caller", "control"),
}


@router.get("/meta")
def meta(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    managed = defn.admin_managed_keys(db)
    attrs = [a for a in profile_catalog.catalog(db)]
    return {
        "triggers": [
            {"type": t, "label": TRIGGER_INFO[t][0], "description": TRIGGER_INFO[t][1],
             "fields": defn.trigger_field_paths(t, db),
             "payload_pills": t in ("manual", "webhook", "call")}
            for t in defn.TRIGGER_TYPES
        ],
        "steps": [{"type": t, "label": STEP_INFO[t][0], "kind": STEP_INFO[t][1], "outputs": defn.STEP_OUTPUTS[t]} for t in defn.STEP_TYPES if t not in defn.PALETTE_HIDDEN],
        "operators": list(cond.OPERATORS),
        "managed_attributes": [
            {"key": a.key, "display_name": a.display_name, "data_type": a.data_type, "enum_options": a.enum_options}
            for a in attrs if a.key in managed
        ],
        "safe_user_fields": sorted(defn._SAFE_USER_FIELDS),
        "limits": {"max_steps": defn.MAX_STEPS, "max_nesting": defn.MAX_NESTING},
        "functions": formula.CATALOG,
        "callable_recipes": calls.callable_recipes(db),
        "lookup_tables": [{"name": t.name, "columns": t.columns, "key_column": t.key_column, "admin_managed": t.admin_managed}
                          for t in db.query(LookupTable).order_by(LookupTable.name).all()],
    }


# ---- jobs (declared before /{id}) ---------------------------------------------------------------------

@router.get("/jobs")
def list_jobs(
    recipe_id: Optional[int] = None,
    status: Optional[str] = Query(None, pattern="^(queued|waiting|running|succeeded|failed|cancelled)$"),
    p: ListParams = Depends(list_params),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    q = db.query(RecipeJob)
    if recipe_id is not None:
        q = q.filter(RecipeJob.recipe_id == recipe_id)
    if status:
        q = q.filter(RecipeJob.status == status)

    def render(rows):
        names = {r.id: r.name for r in db.query(Recipe.id, Recipe.name).filter(Recipe.id.in_({j.recipe_id for j in rows})).all()} if rows else {}
        return [_job_dict(j, names.get(j.recipe_id)) for j in rows]

    return paginate(q, p, sort=JOB_SORT, default_order=[RecipeJob.id.desc()], tiebreak=RecipeJob.id, filter_attrs=JOB_LIST_ATTRS, render=render)


@router.get("/jobs/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    j = db.get(RecipeJob, job_id)
    if j is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_detail(db, j)


@router.post("/jobs/{job_id}/rerun", status_code=202)
def rerun_job(job_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    """Run the same definition and trigger again as a NEW job (Workato-style). At-least-once: effects the first run
    already had (HTTP calls, group changes that were not idempotent) happen again, so this is an explicit admin action."""
    j = db.get(RecipeJob, job_id)
    if j is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if j.mode != "live" or j.status not in ("failed", "cancelled"):
        raise HTTPException(status_code=409, detail="Only failed or cancelled jobs can be re-run")
    r = db.get(Recipe, j.recipe_id)
    if r is not None and not can_manage(actor, r):
        raise HTTPException(status_code=403, detail="Only the owner of this recipe can do that")
    if r is None or not r.enabled:
        raise HTTPException(status_code=409, detail="Enable the recipe before re-running its jobs")
    new = engine.create_job(db, r, j.definition, j.version, j.trigger, f"rerun:{j.id}:{uuid.uuid4().hex[:12]}", depth=j.depth, enforce_rate=False)
    new.rerun_of = j.id
    _audit(db, AuditAction.RECIPE_JOB_RERUN, actor, r.id, {"job_id": new.id, "rerun_of": j.id}, request)
    db.commit()
    return _job_dict(new, r.name)


class DecisionBody(BaseModel):
    comment: Optional[str] = Field(None, max_length=500)


def _decide(job_id: int, decision: str, request: Request, db: Session, actor: User) -> dict:
    j = db.query(RecipeJob).filter(RecipeJob.id == job_id).with_for_update().first()
    if j is None:
        raise HTTPException(status_code=404, detail="Job not found")
    r = db.get(Recipe, j.recipe_id)
    if r is not None and not can_manage(actor, r):
        raise HTTPException(status_code=403, detail="Only the owner of this recipe can do that")
    if j.status != "waiting" or not j.approval or j.approval.get("decision") is not None:
        raise HTTPException(status_code=409, detail="This job is not waiting for a decision")
    if r is None or not r.enabled:
        raise HTTPException(status_code=409, detail="The recipe is disabled; enable it or cancel the job")
    j.approval = {**j.approval, "decision": decision, "decided_by": str(actor.id)}
    j.status, j.next_run_at = "queued", NOW()
    _audit(db, AuditAction.RECIPE_APPROVAL_DECIDED, actor, j.recipe_id,
           {"job_id": j.id, "decision": decision, "step_id": j.approval["step_id"]}, request)
    db.commit()
    return _job_dict(j, r.name)


@router.post("/jobs/{job_id}/approve")
def approve_job(job_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    return _decide(job_id, "approved", request, db, actor)


@router.post("/jobs/{job_id}/deny")
def deny_job(job_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    return _decide(job_id, "denied", request, db, actor)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    """Queued jobs are cancelled at once; a running job stops before its next step (a step already in flight finishes)."""
    j = (db.query(RecipeJob).filter(RecipeJob.id == job_id).with_for_update().first())
    if j is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if j.status not in ("queued", "waiting", "running"):
        raise HTTPException(status_code=409, detail="The job has already finished")
    r = db.get(Recipe, j.recipe_id)
    if r is not None and not can_manage(actor, r):
        raise HTTPException(status_code=403, detail="Only the owner of this recipe can do that")
    if j.status in ("queued", "waiting"):
        engine._finish(db, j, "cancelled", NOW(), "cancelled by an administrator")
        db.commit()
    else:
        j.cancel_requested = True
        _audit(db, AuditAction.RECIPE_JOB_CANCEL_REQUESTED, actor, j.recipe_id, {"job_id": j.id}, request)
        db.commit()
    return _job_dict(j, r.name if r else None)


# ---- metrics ----------------------------------------------------------------------------------------------

@router.get("/metrics")
def metrics(hours: int = Query(24, ge=1, le=168), db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Per-recipe health over the last N hours (live jobs only) plus queue depth. Failure rate = failed / finished."""
    since = NOW() - timedelta(hours=hours)
    rows = (
        db.query(RecipeJob.recipe_id, RecipeJob.status, func.count(RecipeJob.id))
        .filter(RecipeJob.mode == "live", RecipeJob.created_at > since).group_by(RecipeJob.recipe_id, RecipeJob.status).all()
    )
    by: Dict[int, Dict[str, int]] = {}
    for rid, st, n in rows:
        by.setdefault(rid, {})[st] = n
    dur = {
        rid: (p50, p95) for rid, p50, p95 in db.query(
            RecipeJob.recipe_id,
            func.percentile_cont(0.5).within_group(func.extract("epoch", RecipeJob.finished_at - RecipeJob.started_at)),
            func.percentile_cont(0.95).within_group(func.extract("epoch", RecipeJob.finished_at - RecipeJob.started_at)),
        ).filter(RecipeJob.mode == "live", RecipeJob.created_at > since, RecipeJob.finished_at.is_not(None),
                 RecipeJob.started_at.is_not(None), RecipeJob.status.in_(("succeeded", "failed"))).group_by(RecipeJob.recipe_id)
    }
    now = NOW()
    items = []
    for r in db.query(Recipe).order_by(Recipe.id).all():
        c = by.get(r.id, {})
        finished = c.get("succeeded", 0) + c.get("failed", 0)
        p50, p95 = dur.get(r.id, (None, None))
        items.append({
            "recipe_id": r.id, "name": r.name, "enabled": r.enabled, "total": sum(c.values()), "by_status": c,
            "failure_rate": round(c.get("failed", 0) / finished, 3) if finished else None,
            "p50_seconds": round(p50, 2) if p50 is not None else None, "p95_seconds": round(p95, 2) if p95 is not None else None,
            "throttled_count": r.throttled_count or 0,
            "alerting": bool(r.last_alert_at and r.last_alert_at > now - timedelta(minutes=settings.RECIPES_ALERT_WINDOW_MINUTES)),
            "last_alert_at": r.last_alert_at.isoformat() if r.last_alert_at else None,
        })
    oldest = db.query(func.min(RecipeJob.next_run_at)).filter(RecipeJob.mode == "live", RecipeJob.status == "queued").scalar()
    return {
        "window_hours": hours, "items": items,
        "queue": {"queued": db.query(func.count(RecipeJob.id)).filter(RecipeJob.mode == "live", RecipeJob.status == "queued").scalar(),
                  "waiting": db.query(func.count(RecipeJob.id)).filter(RecipeJob.mode == "live", RecipeJob.status == "waiting").scalar(),
                  "oldest_queued_age_seconds": max(int((now - oldest).total_seconds()), 0) if oldest else None},
        "alert_rule": {"min_jobs": settings.RECIPES_ALERT_MIN_JOBS, "failure_rate": settings.RECIPES_ALERT_FAILURE_RATE,
                       "window_minutes": settings.RECIPES_ALERT_WINDOW_MINUTES},
    }


# ---- recipes ----------------------------------------------------------------------------------------------

class RecipeBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    definition: Optional[Dict[str, Any]] = None


@router.get("")
def list_recipes(db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    return {"items": [_recipe_dict(db, r, viewer=actor) for r in db.query(Recipe).order_by(Recipe.id).all()]}


def _create(db: Session, actor: User, request: Request, name: str, description: Optional[str], definition: Any, meta: Optional[dict] = None) -> Recipe:
    if db.query(func.count(Recipe.id)).scalar() >= settings.RECIPES_MAX_RECIPES:
        raise HTTPException(status_code=409, detail=f"At most {settings.RECIPES_MAX_RECIPES} recipes")
    d = _validated(db, definition, actor=actor)
    r = Recipe(public_id=secrets.token_urlsafe(16).replace("-", "a").replace("_", "b")[:22], name=name.strip(),
               description=description, enabled=False, draft=d, created_by=actor.id, owner_id=actor.id, editors=[])
    db.add(r)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Recipe name already in use")
    _audit(db, AuditAction.RECIPE_CREATED, actor, r.id, {"name": r.name, **(meta or {})}, request)
    db.commit()
    return r


@router.post("", status_code=201)
def create_recipe(body: RecipeBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    r = _create(db, actor, request, body.name, body.description, body.definition if body.definition is not None else defn.blank_definition())
    return _recipe_dict(db, r, detail=True, viewer=actor)


# ---- templates, import, export (declared before /{recipe_id}) -------------------------------------------------------

@router.get("/templates")
def list_templates(_: User = Depends(require_admin)):
    return {"items": portable.public_catalog()}


class FromTemplateBody(BaseModel):
    template_id: str = Field(..., max_length=60)
    name: str = Field(..., min_length=1, max_length=100)
    params: Dict[str, Any] = Field(default_factory=dict)


@router.post("/from-template", status_code=201)
def from_template(body: FromTemplateBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    t = portable.BY_ID.get(body.template_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Unknown template")
    p: Dict[str, Any] = {}
    managed = defn.admin_managed_keys(db)
    for spec in t["params"]:
        k, v = spec["key"], body.params.get(spec["key"])
        bad = HTTPException(status_code=422, detail=f"'{spec['label']}' is missing or invalid")
        if spec["type"] == "group":
            g = db.get(Group, v) if isinstance(v, int) and not isinstance(v, bool) else None
            if g is None or g.is_system_group:
                raise bad
        elif spec["type"] == "slack_connection":
            c = db.get(RecipeConnection, v) if isinstance(v, int) and not isinstance(v, bool) else None
            if c is None or c.kind != "slack_webhook":
                raise bad
        elif spec["type"] == "attribute":
            if v not in managed:
                raise bad
        elif spec["type"] == "number":
            if isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 100:
                raise bad
        elif not isinstance(v, str) or not 1 <= len(v) <= 200:
            raise bad
        p[k] = v
    r = _create(db, actor, request, body.name, t["description"], t["build"](p), {"template": t["id"]})
    return _recipe_dict(db, r, detail=True, viewer=actor)


@router.get("/{recipe_id}/export")
def export_recipe(recipe_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    """The DRAFT as a portable document. No secrets, no ids that only mean something here."""
    r = _get(db, recipe_id)
    doc = portable.export_document(db, r)
    _audit(db, AuditAction.RECIPE_EXPORTED, actor, r.id, None, request)
    db.commit()
    return doc


class ImportBody(BaseModel):
    document: Dict[str, Any]
    name: Optional[str] = Field(None, min_length=1, max_length=100)


@router.post("/import", status_code=201)
def import_recipe(body: ImportBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    if len(json.dumps(body.document)) > portable.MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail="The file is too large")
    try:
        name, desc, d, _ = portable.resolve_import(db, body.document)
    except portable.ImportError_ as e:
        raise HTTPException(status_code=422, detail=str(e))
    r = _create(db, actor, request, body.name or name, desc, d, {"imported": True})
    return _recipe_dict(db, r, detail=True, viewer=actor)


class SettingsBody(BaseModel):
    owner_id: Optional[int] = None
    editors: Optional[List[int]] = Field(None, max_length=20)
    rate_limit_per_hour: Optional[int] = Field(None, ge=0, le=100000)
    clear_rate_limit: bool = False  # back to the server default


@router.put("/{recipe_id}/settings")
def update_settings(recipe_id: int, body: SettingsBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    """Owner, editors and the hourly job limit. Owner or super admin only."""
    r = _need(db, recipe_id, actor, "manage")
    changed = {}
    if body.owner_id is not None and body.owner_id != r.owner_id:
        new_owner = db.get(User, body.owner_id)
        if new_owner is None or not new_owner.is_admin or new_owner.status != "active":
            raise HTTPException(status_code=422, detail="The owner must be an active administrator")
        changed["owner_id"] = [r.owner_id, new_owner.id]
        r.owner_id = new_owner.id
    if body.editors is not None:
        ids = sorted({i for i in body.editors if i != r.owner_id})
        found = {u.id for u in db.query(User).filter(User.id.in_(ids), User.is_admin.is_(True), User.status == "active").all()} if ids else set()
        if found != set(ids):
            raise HTTPException(status_code=422, detail="Editors must be active administrators")
        if ids != sorted(r.editors or []):
            changed["editors"] = [sorted(r.editors or []), ids]
        r.editors = ids
    if body.clear_rate_limit:
        changed["rate_limit_per_hour"] = [r.rate_limit_per_hour, None]
        r.rate_limit_per_hour = None
    elif body.rate_limit_per_hour is not None and body.rate_limit_per_hour != r.rate_limit_per_hour:
        changed["rate_limit_per_hour"] = [r.rate_limit_per_hour, body.rate_limit_per_hour]
        r.rate_limit_per_hour = body.rate_limit_per_hour
    if changed:
        r.updated_at = NOW()
        _audit(db, AuditAction.RECIPE_SETTINGS_CHANGED, actor, r.id, {"changed": changed}, request)
    db.commit()
    return _recipe_dict(db, r, detail=True, viewer=actor)


@router.get("/{recipe_id}")
def get_recipe(recipe_id: int, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    return _recipe_dict(db, _get(db, recipe_id), detail=True, viewer=actor)


@router.put("/{recipe_id}")
def update_recipe(recipe_id: int, body: RecipeBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    r = _need(db, recipe_id, actor, "edit")
    if body.definition is not None:
        r.draft = _validated(db, body.definition, actor=actor)
    r.name, r.description, r.updated_at = body.name.strip(), body.description, NOW()
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Recipe name already in use")
    _audit(db, AuditAction.RECIPE_UPDATED, actor, r.id, {"name": r.name}, request)
    db.commit()
    return _recipe_dict(db, r, detail=True, viewer=actor)


@router.delete("/{recipe_id}")
def delete_recipe(recipe_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    r = _need(db, recipe_id, actor, "manage")
    name = r.name
    db.delete(r)
    _audit(db, AuditAction.RECIPE_DELETED, actor, recipe_id, {"name": name}, request)
    db.commit()
    return {"success": True}


def _new_webhook_secret(r: Recipe) -> str:
    secret = secrets.token_urlsafe(32)
    r.webhook_secret_enc = crypto.encrypt(secret)
    return secret


@router.post("/{recipe_id}/publish")
def publish(recipe_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    r = _need(db, recipe_id, actor, "manage")
    d = _validated(db, r.draft, for_publish=True, actor=actor)
    secret = None
    if d["trigger"]["type"] == "webhook":
        if not crypto.available():
            raise HTTPException(status_code=409, detail="Webhook triggers need RECIPE_ENCRYPTION_KEY to be configured")
        if r.webhook_secret_enc is None:
            secret = _new_webhook_secret(r)
    latest = db.query(func.max(RecipeVersion.version)).filter(RecipeVersion.recipe_id == r.id).scalar() or 0
    db.add(RecipeVersion(recipe_id=r.id, version=latest + 1, definition=d, published_by=actor.id, published_at=NOW()))
    r.published_version, r.published_trigger_type, r.updated_at = latest + 1, d["trigger"]["type"], NOW()
    r.draft = d
    _audit(db, AuditAction.RECIPE_PUBLISHED, actor, r.id, {"version": latest + 1, "trigger": d["trigger"]["type"]}, request)
    db.commit()
    out = _recipe_dict(db, r, detail=True, viewer=actor)
    if secret:
        out["webhook_secret"] = secret  # shown once
    return out


@router.post("/{recipe_id}/webhook-secret")
def rotate_webhook_secret(recipe_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    r = _need(db, recipe_id, actor, "manage")
    if not crypto.available():
        raise HTTPException(status_code=409, detail="Webhook triggers need RECIPE_ENCRYPTION_KEY to be configured")
    if "webhook" not in (r.draft["trigger"]["type"], r.published_trigger_type):
        raise HTTPException(status_code=409, detail="This recipe does not use a webhook trigger")
    secret = _new_webhook_secret(r)
    _audit(db, AuditAction.RECIPE_WEBHOOK_SECRET_ROTATED, actor, r.id, None, request)
    db.commit()
    return {"webhook_secret": secret, "webhook_path": f"/api/v1/hooks/recipes/{r.public_id}"}


@router.post("/{recipe_id}/enable")
def enable(recipe_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    r = _need(db, recipe_id, actor, "manage")
    if r.published_version is None:
        raise HTTPException(status_code=409, detail="Publish the recipe before enabling it")
    r.enabled = True
    _audit(db, AuditAction.RECIPE_ENABLED, actor, r.id, None, request)
    db.commit()
    return _recipe_dict(db, r, viewer=actor)


@router.post("/{recipe_id}/disable")
def disable(recipe_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    r = _need(db, recipe_id, actor, "manage")
    r.enabled = False
    _audit(db, AuditAction.RECIPE_DISABLED, actor, r.id, None, request)
    db.commit()
    return _recipe_dict(db, r, viewer=actor)


@router.get("/{recipe_id}/callers")
def callers(recipe_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Recipes that call this one: shown before the callee is changed or published."""
    _get(db, recipe_id)
    return {"callers": calls.callers_of(db, recipe_id)}


@router.get("/{recipe_id}/versions")
def versions(recipe_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    _get(db, recipe_id)
    rows = db.query(RecipeVersion).filter(RecipeVersion.recipe_id == recipe_id).order_by(RecipeVersion.version.desc()).all()
    return {"items": [{"version": v.version, "published_at": v.published_at.isoformat(), "published_by": v.published_by} for v in rows]}


@router.get("/{recipe_id}/versions/{version}")
def get_version(recipe_id: int, version: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    v = db.query(RecipeVersion).filter(RecipeVersion.recipe_id == recipe_id, RecipeVersion.version == version).first()
    if v is None:
        raise HTTPException(status_code=404, detail="Version not found")
    return {"version": v.version, "published_at": v.published_at.isoformat(), "definition": v.definition}


@router.post("/{recipe_id}/versions/{version}/restore")
def restore_version(recipe_id: int, version: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    """Copy a published version into the draft. Nothing is published or enabled; the published version is untouched."""
    r = _need(db, recipe_id, actor, "edit")
    v = db.query(RecipeVersion).filter(RecipeVersion.recipe_id == recipe_id, RecipeVersion.version == version).first()
    if v is None:
        raise HTTPException(status_code=404, detail="Version not found")
    r.draft = _validated(db, v.definition, actor=actor)   # the catalog may have changed since: say so rather than save a broken draft
    r.updated_at = NOW()
    _audit(db, AuditAction.RECIPE_UPDATED, actor, r.id, {"name": r.name, "restored_version": version}, request)
    db.commit()
    return _recipe_dict(db, r, detail=True, viewer=actor)


class RunBody(BaseModel):
    user_id: Optional[int] = None
    group_id: Optional[int] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


def _payload_ok(payload: dict) -> dict:
    def depth(o, d=0):
        if d > 8:
            raise HTTPException(status_code=422, detail="payload is nested too deeply")
        if isinstance(o, dict):
            for v in o.values():
                depth(v, d + 1)
        elif isinstance(o, list):
            for v in o:
                depth(v, d + 1)

    depth(payload)
    if len(json.dumps(payload)) > 16384:
        raise HTTPException(status_code=422, detail="payload is too large")
    return payload


def _sample_trigger(db: Session, d: dict, body: RunBody, admin: User) -> dict:
    from backend.app.recipes.events import user_snapshot

    t = d["trigger"]["type"]
    now = NOW().isoformat()
    ctx: Dict[str, Any] = {"event": {"id": 0, "type": t, "occurred_at": now}, "actor": {"type": "user", "id": str(admin.id)}}
    if t in ("manual", "webhook", "call"):
        ctx["payload"] = _payload_ok(body.payload)
        if t == "manual":
            ctx["manual"] = {"started_by": admin.id}
    needs_user = t not in ("schedule", "webhook", "call")
    if needs_user and (body.user_id is not None or t != "manual"):
        user = db.get(User, body.user_id) if body.user_id is not None else None
        if user is None:
            raise HTTPException(status_code=422, detail="Choose a user to build the sample event from")
        ctx["user"] = user_snapshot(user)
    if t.startswith("group.member_"):
        gid = body.group_id or d["trigger"]["config"].get("group_id")
        g = db.get(Group, gid) if gid else None
        if g is None:
            raise HTTPException(status_code=422, detail="Choose a group to build the sample event from")
        ctx["group"] = {"id": g.id, "name": g.name}
    if t == "user.attribute_changed":
        p = body.payload
        ctx["attribute"] = {"key": d["trigger"]["config"]["attribute"], "old": p.get("old"), "new": p.get("new")}
    if t == "login.failed":
        ctx["login"] = {"consecutive_failures": max(1, d["trigger"]["config"].get("min_failures", 1))}
    if t == "schedule":
        ctx["schedule"] = {"scheduled_for": now}
    return ctx


@router.post("/{recipe_id}/test")
def test_run(recipe_id: int, body: RunBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    """Dry run of the DRAFT: nothing is written and no request is sent."""
    r = _need(db, recipe_id, actor, "edit")
    d = _validated(db, r.draft, actor=actor)
    ctx = _sample_trigger(db, d, body, actor)
    _audit(db, AuditAction.RECIPE_TEST_RUN, actor, r.id, {"trigger": d["trigger"]["type"]}, request)
    job = engine.run_dry(db, r, d, ctx)
    return _job_detail(db, job)


class PreviewBody(RunBody):
    templates: List[str] = Field(default_factory=list, max_length=20)


@router.post("/{recipe_id}/formula-preview")
def formula_preview(recipe_id: int, body: PreviewBody, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    """Evaluate fields (pills and formulas) against a sample event. Reads only; earlier steps' outputs are not available."""
    r = _need(db, recipe_id, actor, "edit")
    d = _validated(db, r.draft, actor=actor)
    data = {"trigger": _sample_trigger(db, d, body, actor), "steps": {}, "recipe": {"id": r.id, "name": r.name, "version": 0}, "job": {"id": 0}}
    items = []
    for t in body.templates:
        if len(t) > 2000:
            items.append({"template": t[:50], "ok": False, "error": "too long"})
            continue
        try:
            items.append({"template": t, "ok": True, "value": tpl.render(t, data)})
        except tpl.TemplateError as e:
            items.append({"template": t, "ok": False, "error": str(e)})
    return {"items": items}


@router.post("/{recipe_id}/run", status_code=202)
def manual_run(recipe_id: int, body: RunBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    r = _need(db, recipe_id, actor, "manage")
    if r.published_version is None or not r.enabled:
        raise HTTPException(status_code=409, detail="Publish and enable the recipe before running it")
    if r.published_trigger_type != "manual":
        raise HTTPException(status_code=409, detail="Only recipes with a manual trigger can be started by hand")
    v = db.query(RecipeVersion).filter(RecipeVersion.recipe_id == r.id, RecipeVersion.version == r.published_version).one()
    ctx = _sample_trigger(db, v.definition, body, actor)
    job = engine.create_job(db, r, v.definition, v.version, ctx, f"manual:{uuid.uuid4().hex}", enforce_rate=False)
    _audit(db, AuditAction.RECIPE_MANUAL_RUN, actor, r.id, {"job_id": job.id, "version": v.version}, request)
    db.commit()
    return _job_dict(job, r.name)


# ---- connections -----------------------------------------------------------------------------------------------

_HOST = re.compile(r"^[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?$")
_HEADER = re.compile(r"^[A-Za-z0-9-]{1,100}$")
_FORBIDDEN = {"host", "content-length", "transfer-encoding", "connection", "upgrade", "te", "trailer", "expect"}


class ConnectionBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    kind: str = Field(..., pattern="^(bearer|header|oauth2_client_credentials|slack_webhook)$")
    header_name: Optional[str] = Field(None, max_length=100)
    allowed_host: str = Field("", max_length=255)
    allowed_paths: Optional[List[str]] = Field(None, max_length=20)
    client_id: Optional[str] = Field(None, max_length=255)
    token_url: Optional[str] = Field(None, max_length=2000)
    scope: Optional[str] = Field(None, max_length=500)
    secret: Optional[str] = Field(None, min_length=1, max_length=2000)
    allowed_users: Optional[List[int]] = Field(None, max_length=50)  # admin ids; empty/None = every administrator


def _conn_dict(c: RecipeConnection, viewer: Optional[User] = None) -> dict:
    from backend.app.recipes import access

    manage = viewer is None or access.can_manage_connection(viewer, c)
    return {  # the secret is never part of any response
        "restricted": access.restricted(c), "can_use": viewer is None or access.can_use_connection(viewer, c),
        "can_manage": manage, "allowed_users": (c.allowed_users or []) if manage else None,
        "id": c.id, "name": c.name, "kind": c.kind, "header_name": c.header_name, "allowed_host": c.allowed_host,
        "allowed_paths": c.allowed_paths or [], "client_id": c.client_id, "token_url": c.token_url, "scope": c.scope,
        "connector_id": c.connector_id, "connector_version": c.connector_version, "config": c.config or {},
        "has_secret": True, "created_at": c.created_at.isoformat(), "updated_at": c.updated_at.isoformat(),
    }


_PATH = re.compile(r"^/[A-Za-z0-9._~!$&'()*+,;=:@/%-]{0,199}$")
SLACK_HOST = "hooks.slack.com"


def _conn_checks(body: ConnectionBody) -> str:
    host = SLACK_HOST if body.kind == "slack_webhook" else body.allowed_host.strip().lower()
    if not _HOST.match(host):
        raise HTTPException(status_code=422, detail="allowed_host must be a bare host name such as api.example.com")
    if body.kind == "header":
        if not body.header_name or not _HEADER.match(body.header_name) or body.header_name.lower() in _FORBIDDEN:
            raise HTTPException(status_code=422, detail="header_name is required and must be a valid header name")
    if body.kind == "slack_webhook":
        if body.allowed_paths:
            raise HTTPException(status_code=422, detail="path lists do not apply to Slack connections")
        if body.secret and not body.secret.startswith("https://hooks.slack.com/services/"):
            raise HTTPException(status_code=422, detail="the secret must be a Slack incoming webhook URL (https://hooks.slack.com/services/...)")
    for p in body.allowed_paths or []:
        if not _PATH.match(p) or ".." in p or "//" in p or re.search(r"%(2e|2f|5c)", p, re.I):
            raise HTTPException(status_code=422, detail=f"invalid allowed path {p!r}: use plain path prefixes such as /api/v1/")
    if body.kind == "oauth2_client_credentials":
        if not body.client_id or not body.token_url:
            raise HTTPException(status_code=422, detail="client_id and token_url are required for OAuth2 connections")
        from urllib.parse import urlsplit
        try:
            u = urlsplit(body.token_url)
            ok = u.scheme == "https" and (u.hostname or "").lower() == host and not u.username and not u.password
        except ValueError:
            ok = False
        if not ok:
            raise HTTPException(status_code=422, detail="token_url must be an https URL on the connection's allowed host")
    if body.secret and ("\r" in body.secret or "\n" in body.secret):
        raise HTTPException(status_code=422, detail="secret contains invalid characters")
    return host


def _need_key():
    if not crypto.available():
        raise HTTPException(status_code=409, detail="Connections are not available: RECIPE_ENCRYPTION_KEY is not configured")


def _apply_extras(c: RecipeConnection, body: ConnectionBody) -> None:
    c.allowed_paths = sorted(set(body.allowed_paths)) if body.allowed_paths else None
    oauth = body.kind == "oauth2_client_credentials"
    c.client_id, c.token_url, c.scope = (body.client_id, body.token_url, body.scope or None) if oauth else (None, None, None)


def _acl_ids(db: Session, ids: Optional[List[int]]) -> Optional[List[int]]:
    """Validate the allow-list: every id must be an administrator of this tenant. Empty means no restriction."""
    ids = sorted(set(ids or []))
    if not ids:
        return None
    found = {u for (u,) in db.query(User.id).filter(User.id.in_(ids), User.is_admin.is_(True)).all()}
    if found != set(ids):
        raise HTTPException(status_code=422, detail="allowed_users must be administrators")
    return ids


@connections_router.get("")
def list_connections(db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    return {"items": [_conn_dict(c, actor) for c in db.query(RecipeConnection).order_by(RecipeConnection.id).all()]}


@connections_router.post("", status_code=201)
def create_connection(body: ConnectionBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    _need_key()
    host = _conn_checks(body)
    if not body.secret:
        raise HTTPException(status_code=422, detail="secret is required")
    c = RecipeConnection(name=body.name.strip(), kind=body.kind, header_name=body.header_name if body.kind == "header" else None,
                         allowed_host=host, secret_enc=crypto.encrypt(body.secret), created_by=actor.id)
    _apply_extras(c, body)
    c.allowed_users = _acl_ids(db, body.allowed_users)
    db.add(c)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Connection name already in use")
    record(db, AuditAction.RECIPE_CONNECTION_CREATED, request, actor, c.id, "recipe_connection", {"name": c.name, "host": host})
    db.commit()
    return _conn_dict(c, actor)


@connections_router.put("/{cid}")
def update_connection(cid: int, body: ConnectionBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    c = db.get(RecipeConnection, cid)
    if c is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    from backend.app.recipes import access

    if not access.can_manage_connection(actor, c):
        raise HTTPException(status_code=403, detail="Only the creator of this connection or a super admin can change it")
    if c.connector_id:
        raise HTTPException(status_code=409, detail="This is a connector connection: change it through /admin/connectors")
    _need_key()
    host = _conn_checks(body)
    c.name, c.kind, c.allowed_host = body.name.strip(), body.kind, host
    if body.allowed_users is not None:
        c.allowed_users = _acl_ids(db, body.allowed_users)
    c.header_name = body.header_name if body.kind == "header" else None
    _apply_extras(c, body)
    rotated = bool(body.secret)
    if body.secret:
        c.secret_enc = crypto.encrypt(body.secret)
    c.updated_at = NOW()
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Connection name already in use")
    record(db, AuditAction.RECIPE_CONNECTION_UPDATED, request, actor, c.id, "recipe_connection",
           {"name": c.name, "secret_rotated": rotated, "restricted": bool(c.allowed_users)})
    db.commit()
    return _conn_dict(c, actor)


def _holds_connection(node: Any, cid: int) -> bool:
    if isinstance(node, dict):
        return node.get("connection_id") == cid or any(_holds_connection(v, cid) for v in node.values())
    if isinstance(node, list):
        return any(_holds_connection(v, cid) for v in node)
    return False


def _recipes_using_connection(db: Session, cid: int) -> List[str]:
    """Recipes whose draft or published version has a step using the connection."""
    out = []
    for r in db.query(Recipe).order_by(Recipe.id).all():
        defs = [r.draft or {}]
        if r.published_version:
            v = db.query(RecipeVersion).filter(RecipeVersion.recipe_id == r.id, RecipeVersion.version == r.published_version).first()
            if v:
                defs.append(v.definition or {})
        if any(_holds_connection(d, cid) for d in defs):
            out.append(r.name)
    return out


@connections_router.delete("/{cid}")
def delete_connection(cid: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    c = db.get(RecipeConnection, cid)
    if c is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    from backend.app.recipes import access

    if not access.can_manage_connection(actor, c):
        raise HTTPException(status_code=403, detail="Only the creator of this connection or a super admin can delete it")
    name = c.name
    if c.connector_id:
        used = _recipes_using_connection(db, cid)
        if used:
            raise HTTPException(status_code=409, detail="Used by recipes: " + ", ".join(used[:5]) + ". Remove or change those steps first.")
    db.delete(c)
    record(db, AuditAction.RECIPE_CONNECTION_DELETED, request, actor, cid, "recipe_connection", {"name": name})
    db.commit()
    return {"success": True}


# ---- inbound webhook -----------------------------------------------------------------------------------------------

def sign_webhook(secret: str, timestamp: str, body: bytes) -> str:
    return hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


@hooks_router.post("/{public_id}")
async def webhook(public_id: str, request: Request, db: Session = Depends(get_db)):
    if not settings.RECIPES_ENABLED:
        raise HTTPException(status_code=404, detail="Not found")
    ip = ratelimit.client_ip(request)
    ratelimit.check("recipe_hook", ip, 30)
    limit = settings.RECIPES_WEBHOOK_MAX_BODY_BYTES
    if int(request.headers.get("content-length", "0") or 0) > limit:
        raise HTTPException(status_code=413, detail="Payload too large")
    body = await request.body()
    if len(body) > limit:
        raise HTTPException(status_code=413, detail="Payload too large")

    r = db.query(Recipe).filter(Recipe.public_id == public_id[:64]).first()
    if r is None or not r.enabled or r.published_trigger_type != "webhook" or r.webhook_secret_enc is None:
        raise HTTPException(status_code=404, detail="Not found")
    try:
        secret = crypto.decrypt(r.webhook_secret_enc)
    except crypto.RecipeKeyError:
        raise HTTPException(status_code=404, detail="Not found")

    def reject():
        ratelimit.hit("recipe_hook", ip, 300)
        return HTTPException(status_code=401, detail="Invalid signature")

    # X-Ifora-* is the current name; the X-IdentityForge-* names from before the rebrand keep working (existing senders).
    ts = request.headers.get("x-ifora-timestamp", "") or request.headers.get("x-identityforge-timestamp", "")
    sig = request.headers.get("x-ifora-signature", "") or request.headers.get("x-identityforge-signature", "")
    if not ts.isdigit() or len(ts) > 12 or not sig.startswith("v1="):
        raise reject()
    if abs(time.time() - int(ts)) > settings.RECIPES_WEBHOOK_REPLAY_SECONDS:
        raise reject()
    expected = sign_webhook(secret, ts, body)
    if not hmac.compare_digest(sig[3:].lower(), expected):
        raise reject()

    try:
        payload = json.loads(body) if body.strip() else {}
    except ValueError:
        raise HTTPException(status_code=422, detail="Body must be JSON")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Body must be a JSON object")
    _payload_ok(payload)

    v = db.query(RecipeVersion).filter(RecipeVersion.recipe_id == r.id, RecipeVersion.version == r.published_version).one()
    now = NOW()
    ctx = {"event": {"id": 0, "type": "webhook", "occurred_at": now.isoformat()},
           "actor": {"type": "webhook", "id": ""}, "payload": payload}
    if not engine.trigger_matches(db, v.definition["trigger"], ctx):
        return {"accepted": False}
    try:
        job = engine.create_job(db, r, v.definition, v.version, ctx, "wh:" + expected, now=now)
    except engine.RateLimited:
        db.commit()  # keep the throttle counters and the audit line
        raise HTTPException(status_code=429, detail="This recipe is over its hourly limit", headers={"Retry-After": "300"})
    if job is None:  # replay of an already accepted request: same signature, same job
        return {"accepted": True, "duplicate": True}
    db.add(AuditEvent(
        action=AuditAction.RECIPE_WEBHOOK_RECEIVED, actor_id=f"webhook:{r.id}", actor_type="webhook",
        target_id=str(r.id), target_type="recipe", metadata={"job_id": job.id, "version": v.version},
    ))
    db.commit()
    return {"accepted": True, "job_id": job.id}
