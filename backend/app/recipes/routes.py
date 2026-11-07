"""Admin API for recipes, connections and job history, plus the signed inbound webhook (ADR 008)."""

import hashlib
import hmac
import json
import re
import secrets
import time
import uuid
from datetime import datetime, timezone
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
from backend.app.profiles import catalog as profile_catalog
from backend.app.recipes import conditions as cond
from backend.app.recipes import crypto, definition as defn, engine
from backend.app.recipes.models import (
    Recipe, RecipeConnection, RecipeJob, RecipeJobStep, RecipeVersion,
)
from backend.app.recipes.redact import redact
from backend.app.users.model import User


def _enabled():
    if not settings.RECIPES_ENABLED:
        raise HTTPException(status_code=404, detail="Recipes are not enabled")


router = APIRouter(prefix="/admin/recipes", tags=["recipes"], dependencies=[Depends(_enabled)])
connections_router = APIRouter(prefix="/admin/recipe-connections", tags=["recipes"], dependencies=[Depends(_enabled)])
hooks_router = APIRouter(prefix="/hooks/recipes", tags=["recipes"])

NOW = lambda: datetime.now(timezone.utc)  # noqa: E731


# ---- serialisation ---------------------------------------------------------------------------------

def _recipe_dict(db: Session, r: Recipe, detail: bool = False) -> dict:
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
    }
    if detail:
        d["draft"] = r.draft
    return d


def _job_dict(j: RecipeJob, name: Optional[str] = None) -> dict:
    return {
        "id": j.id, "recipe_id": j.recipe_id, "recipe_name": name, "version": j.version, "mode": j.mode,
        "status": j.status, "trigger_type": j.trigger_type, "depth": j.depth, "executed_steps": j.executed_steps,
        "attempt": j.attempt, "error": j.error, "in_handler": j.in_handler, "cancel_requested": j.cancel_requested,
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


def _validated(db: Session, definition: Any, for_publish: bool = False) -> dict:
    try:
        return defn.validate_definition(db, definition, for_publish=for_publish)
    except defn.DefinitionError as e:
        raise HTTPException(status_code=422, detail=str(e))


def _audit(db, action, actor, r_id, meta=None, request=None):
    record(db, action, request, actor, r_id, "recipe", meta)


# ---- status / meta ----------------------------------------------------------------------------------

@router.get("/status")
def status(_: User = Depends(require_admin)):
    ok = crypto.available()
    seen = engine.worker_last_seen()
    return {"enabled": True, "connections_available": ok, "webhooks_available": ok,
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
    "schedule": ("On a schedule", "Runs every N minutes (5 to 1440)."),
    "manual": ("Run manually", "Started by an administrator with the Run button."),
    "webhook": ("An external system calls a webhook", "Signed with a per-recipe secret (HMAC-SHA256)."),
}
STEP_INFO = {
    "add_to_group": ("Add user to group", "action"), "remove_from_group": ("Remove user from group", "action"),
    "set_attribute": ("Set a profile attribute", "action"), "activate_user": ("Activate user", "action"),
    "deactivate_user": ("Deactivate user", "action"), "http_request": ("Send an HTTP request", "action"),
    "log": ("Write to the job log", "action"), "condition": ("If / else", "control"), "stop": ("Stop", "control"),
}


@router.get("/meta")
def meta(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    managed = defn.admin_managed_keys(db)
    attrs = [a for a in profile_catalog.catalog(db)]
    return {
        "triggers": [
            {"type": t, "label": TRIGGER_INFO[t][0], "description": TRIGGER_INFO[t][1],
             "fields": defn.trigger_field_paths(t, db),
             "payload_pills": t in ("manual", "webhook")}
            for t in defn.TRIGGER_TYPES
        ],
        "steps": [{"type": t, "label": STEP_INFO[t][0], "kind": STEP_INFO[t][1], "outputs": defn.STEP_OUTPUTS[t]} for t in defn.STEP_TYPES],
        "operators": list(cond.OPERATORS),
        "managed_attributes": [
            {"key": a.key, "display_name": a.display_name, "data_type": a.data_type, "enum_options": a.enum_options}
            for a in attrs if a.key in managed
        ],
        "safe_user_fields": sorted(defn._SAFE_USER_FIELDS),
        "limits": {"max_steps": defn.MAX_STEPS, "max_nesting": defn.MAX_NESTING},
    }


# ---- jobs (declared before /{id}) ---------------------------------------------------------------------

@router.get("/jobs")
def list_jobs(
    recipe_id: Optional[int] = None,
    status: Optional[str] = Query(None, pattern="^(queued|running|succeeded|failed|cancelled)$"),
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    q = db.query(RecipeJob)
    if recipe_id is not None:
        q = q.filter(RecipeJob.recipe_id == recipe_id)
    if status:
        q = q.filter(RecipeJob.status == status)
    total = q.count()
    rows = q.order_by(RecipeJob.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    names = {r.id: r.name for r in db.query(Recipe.id, Recipe.name).filter(Recipe.id.in_({j.recipe_id for j in rows})).all()} if rows else {}
    return {"items": [_job_dict(j, names.get(j.recipe_id)) for j in rows], "total": total, "page": page, "page_size": page_size}


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
    if r is None or not r.enabled:
        raise HTTPException(status_code=409, detail="Enable the recipe before re-running its jobs")
    new = engine.create_job(db, r, j.definition, j.version, j.trigger, f"rerun:{j.id}:{uuid.uuid4().hex[:12]}", depth=j.depth)
    new.rerun_of = j.id
    _audit(db, AuditAction.RECIPE_JOB_RERUN, actor, r.id, {"job_id": new.id, "rerun_of": j.id}, request)
    db.commit()
    return _job_dict(new, r.name)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    """Queued jobs are cancelled at once; a running job stops before its next step (a step already in flight finishes)."""
    j = (db.query(RecipeJob).filter(RecipeJob.id == job_id).with_for_update().first())
    if j is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if j.status not in ("queued", "running"):
        raise HTTPException(status_code=409, detail="The job has already finished")
    r = db.get(Recipe, j.recipe_id)
    if j.status == "queued":
        engine._finish(db, j, "cancelled", NOW(), "cancelled by an administrator")
        db.commit()
    else:
        j.cancel_requested = True
        _audit(db, AuditAction.RECIPE_JOB_CANCEL_REQUESTED, actor, j.recipe_id, {"job_id": j.id}, request)
        db.commit()
    return _job_dict(j, r.name if r else None)


# ---- recipes ----------------------------------------------------------------------------------------------

class RecipeBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    definition: Optional[Dict[str, Any]] = None


@router.get("")
def list_recipes(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return {"items": [_recipe_dict(db, r) for r in db.query(Recipe).order_by(Recipe.id).all()]}


@router.post("", status_code=201)
def create_recipe(body: RecipeBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    if db.query(func.count(Recipe.id)).scalar() >= settings.RECIPES_MAX_RECIPES:
        raise HTTPException(status_code=409, detail=f"At most {settings.RECIPES_MAX_RECIPES} recipes")
    d = _validated(db, body.definition if body.definition is not None else defn.blank_definition())
    r = Recipe(public_id=secrets.token_urlsafe(16).replace("-", "a").replace("_", "b")[:22], name=body.name.strip(),
               description=body.description, enabled=False, draft=d, created_by=actor.id)
    db.add(r)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Recipe name already in use")
    _audit(db, AuditAction.RECIPE_CREATED, actor, r.id, {"name": r.name}, request)
    db.commit()
    return _recipe_dict(db, r, detail=True)


@router.get("/{recipe_id}")
def get_recipe(recipe_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return _recipe_dict(db, _get(db, recipe_id), detail=True)


@router.put("/{recipe_id}")
def update_recipe(recipe_id: int, body: RecipeBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    r = _get(db, recipe_id)
    if body.definition is not None:
        r.draft = _validated(db, body.definition)
    r.name, r.description, r.updated_at = body.name.strip(), body.description, NOW()
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Recipe name already in use")
    _audit(db, AuditAction.RECIPE_UPDATED, actor, r.id, {"name": r.name}, request)
    db.commit()
    return _recipe_dict(db, r, detail=True)


@router.delete("/{recipe_id}")
def delete_recipe(recipe_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    r = _get(db, recipe_id)
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
    r = _get(db, recipe_id)
    d = _validated(db, r.draft, for_publish=True)
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
    out = _recipe_dict(db, r, detail=True)
    if secret:
        out["webhook_secret"] = secret  # shown once
    return out


@router.post("/{recipe_id}/webhook-secret")
def rotate_webhook_secret(recipe_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    r = _get(db, recipe_id)
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
    r = _get(db, recipe_id)
    if r.published_version is None:
        raise HTTPException(status_code=409, detail="Publish the recipe before enabling it")
    r.enabled = True
    _audit(db, AuditAction.RECIPE_ENABLED, actor, r.id, None, request)
    db.commit()
    return _recipe_dict(db, r)


@router.post("/{recipe_id}/disable")
def disable(recipe_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    r = _get(db, recipe_id)
    r.enabled = False
    _audit(db, AuditAction.RECIPE_DISABLED, actor, r.id, None, request)
    db.commit()
    return _recipe_dict(db, r)


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
    if t in ("manual", "webhook"):
        ctx["payload"] = _payload_ok(body.payload)
        if t == "manual":
            ctx["manual"] = {"started_by": admin.id}
    needs_user = t not in ("schedule", "webhook")
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
    r = _get(db, recipe_id)
    d = _validated(db, r.draft)
    ctx = _sample_trigger(db, d, body, actor)
    _audit(db, AuditAction.RECIPE_TEST_RUN, actor, r.id, {"trigger": d["trigger"]["type"]}, request)
    job = engine.run_dry(db, r, d, ctx)
    return _job_detail(db, job)


@router.post("/{recipe_id}/run", status_code=202)
def manual_run(recipe_id: int, body: RunBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    r = _get(db, recipe_id)
    if r.published_version is None or not r.enabled:
        raise HTTPException(status_code=409, detail="Publish and enable the recipe before running it")
    if r.published_trigger_type != "manual":
        raise HTTPException(status_code=409, detail="Only recipes with a manual trigger can be started by hand")
    v = db.query(RecipeVersion).filter(RecipeVersion.recipe_id == r.id, RecipeVersion.version == r.published_version).one()
    ctx = _sample_trigger(db, v.definition, body, actor)
    job = engine.create_job(db, r, v.definition, v.version, ctx, f"manual:{uuid.uuid4().hex}")
    _audit(db, AuditAction.RECIPE_MANUAL_RUN, actor, r.id, {"job_id": job.id, "version": v.version}, request)
    db.commit()
    return _job_dict(job, r.name)


# ---- connections -----------------------------------------------------------------------------------------------

_HOST = re.compile(r"^[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?$")
_HEADER = re.compile(r"^[A-Za-z0-9-]{1,100}$")
_FORBIDDEN = {"host", "content-length", "transfer-encoding", "connection", "upgrade", "te", "trailer", "expect"}


class ConnectionBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    kind: str = Field(..., pattern="^(bearer|header)$")
    header_name: Optional[str] = Field(None, max_length=100)
    allowed_host: str = Field(..., min_length=1, max_length=255)
    secret: Optional[str] = Field(None, min_length=1, max_length=2000)


def _conn_dict(c: RecipeConnection) -> dict:
    return {  # the secret is never part of any response
        "id": c.id, "name": c.name, "kind": c.kind, "header_name": c.header_name, "allowed_host": c.allowed_host,
        "has_secret": True, "created_at": c.created_at.isoformat(), "updated_at": c.updated_at.isoformat(),
    }


def _conn_checks(body: ConnectionBody) -> str:
    host = body.allowed_host.strip().lower()
    if not _HOST.match(host):
        raise HTTPException(status_code=422, detail="allowed_host must be a bare host name such as api.example.com")
    if body.kind == "header":
        if not body.header_name or not _HEADER.match(body.header_name) or body.header_name.lower() in _FORBIDDEN:
            raise HTTPException(status_code=422, detail="header_name is required and must be a valid header name")
    if body.secret and ("\r" in body.secret or "\n" in body.secret):
        raise HTTPException(status_code=422, detail="secret contains invalid characters")
    return host


def _need_key():
    if not crypto.available():
        raise HTTPException(status_code=409, detail="Connections are not available: RECIPE_ENCRYPTION_KEY is not configured")


@connections_router.get("")
def list_connections(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return {"items": [_conn_dict(c) for c in db.query(RecipeConnection).order_by(RecipeConnection.id).all()]}


@connections_router.post("", status_code=201)
def create_connection(body: ConnectionBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    _need_key()
    host = _conn_checks(body)
    if not body.secret:
        raise HTTPException(status_code=422, detail="secret is required")
    c = RecipeConnection(name=body.name.strip(), kind=body.kind, header_name=body.header_name if body.kind == "header" else None,
                         allowed_host=host, secret_enc=crypto.encrypt(body.secret), created_by=actor.id)
    db.add(c)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Connection name already in use")
    record(db, AuditAction.RECIPE_CONNECTION_CREATED, request, actor, c.id, "recipe_connection", {"name": c.name, "host": host})
    db.commit()
    return _conn_dict(c)


@connections_router.put("/{cid}")
def update_connection(cid: int, body: ConnectionBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    c = db.get(RecipeConnection, cid)
    if c is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    _need_key()
    host = _conn_checks(body)
    c.name, c.kind, c.allowed_host = body.name.strip(), body.kind, host
    c.header_name = body.header_name if body.kind == "header" else None
    rotated = bool(body.secret)
    if body.secret:
        c.secret_enc = crypto.encrypt(body.secret)
    c.updated_at = NOW()
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Connection name already in use")
    record(db, AuditAction.RECIPE_CONNECTION_UPDATED, request, actor, c.id, "recipe_connection", {"name": c.name, "secret_rotated": rotated})
    db.commit()
    return _conn_dict(c)


@connections_router.delete("/{cid}")
def delete_connection(cid: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    c = db.get(RecipeConnection, cid)
    if c is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    name = c.name
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

    ts = request.headers.get("x-identityforge-timestamp", "")
    sig = request.headers.get("x-identityforge-signature", "")
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
    job = engine.create_job(db, r, v.definition, v.version, ctx, "wh:" + expected, now=now)
    if job is None:  # replay of an already accepted request: same signature, same job
        return {"accepted": True, "duplicate": True}
    db.add(AuditEvent(
        action=AuditAction.RECIPE_WEBHOOK_RECEIVED, actor_id=f"webhook:{r.id}", actor_type="webhook",
        target_id=str(r.id), target_type="recipe", metadata={"job_id": job.id, "version": v.version},
    ))
    db.commit()
    return {"accepted": True, "job_id": job.id}
