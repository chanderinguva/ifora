"""Admin API for outbound provisioning apps (ADR 009). Reading and assignments: any admin. Creating, changing,
testing, syncing and deleting an app (it holds a credential and chooses where user data goes): super admins."""

import ipaddress
from urllib.parse import urlsplit
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.auth.deps import require_admin
from backend.app.config import settings
from backend.app.db import get_db
from backend.app.groups.model import Group
from backend.app.profiles import catalog as profile_catalog
from backend.app.provisioning import adapters, mapping, service
from backend.app.provisioning.models import ProvisioningApp, ProvisioningAssignment, ProvisioningLink, ProvisioningTask
from backend.app.provisioning.presets import PRESETS
from backend.app.recipes import crypto
from backend.app.recipes import http_client as hc
from backend.app.users.model import User


def _enabled():
    if not settings.PROVISIONING_ENABLED:
        raise HTTPException(status_code=404, detail="Not found")


router = APIRouter(prefix="/admin/provisioning-apps", tags=["provisioning"], dependencies=[Depends(_enabled)])
MAX_APPS = 50


def _super(user: User = Depends(require_admin)) -> User:
    if not user.is_super_admin:
        raise HTTPException(status_code=403, detail="Only a super admin can do that")
    return user


class Options(BaseModel):
    push_new_users: bool = True
    push_updates: bool = True
    push_groups: bool = False
    deactivate: str = Field("patch", pattern="^(patch|delete|none)$")
    update_style: str = Field("put", pattern="^(put|patch)$")
    user_identifier: str = Field("email", pattern="^(email|username)$")


class AppBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    kind: str = Field(..., pattern="^(scim|rest)$")
    base_url: str = Field(..., min_length=8, max_length=2000)
    auth_type: str = Field(..., pattern="^(bearer|basic|header|oauth2)$")
    token_url: Optional[str] = Field(None, max_length=2000)  # oauth2
    client_id: Optional[str] = Field(None, max_length=255)
    scope: Optional[str] = Field(None, max_length=500)
    header_name: Optional[str] = Field(None, max_length=100)
    secret: Optional[str] = Field(None, min_length=1, max_length=2000)  # required on create; blank on update keeps the old one
    enabled: Optional[bool] = None
    options: Options = Options()
    mapping: List[Dict[str, str]] = Field(default_factory=list)
    rest_config: Optional[Dict[str, Any]] = None


def _need_key() -> None:
    if not crypto.available():
        raise HTTPException(status_code=409, detail="Provisioning apps are not available: RECIPE_ENCRYPTION_KEY is not configured")


def _checked(db: Session, body: AppBody) -> Dict[str, Any]:
    url = body.base_url.strip()
    try:
        scheme, host, port, path = hc.validate_url(url, adapters.http_overrides.get("policy") or hc.EgressPolicy.from_settings())
    except hc.EgressBlocked as e:
        raise HTTPException(status_code=422, detail=f"base_url: {e}")
    pol = adapters.http_overrides.get("policy") or hc.EgressPolicy.from_settings()
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal = None
    if (literal is not None and not hc.ip_allowed(str(literal), pol)) or host.lower() in ("localhost", "localhost.localdomain") or host.lower().endswith(".internal"):
        raise HTTPException(status_code=422, detail="base_url must be a public host (private and loopback addresses are blocked)")
    if scheme != "https":
        raise HTTPException(status_code=422, detail="base_url must use https (credentials are sent with every request)")
    if "?" in url or "#" in url:
        raise HTTPException(status_code=422, detail="base_url must not contain a query or fragment")
    if body.auth_type == "header":
        h = (body.header_name or "").strip()
        if not h or h.lower() in ("host", "content-length", "content-type", "transfer-encoding", "connection"):
            raise HTTPException(status_code=422, detail="a usable header_name is required for header authentication")
    if body.auth_type == "oauth2":
        if not body.client_id or not body.token_url:
            raise HTTPException(status_code=422, detail="client_id and token_url are required for OAuth2")
        try:
            t_scheme, t_host, _p, _x = hc.validate_url(body.token_url.strip(), pol)
        except hc.EgressBlocked as e:
            raise HTTPException(status_code=422, detail=f"token_url: {e}")
        if t_scheme != "https" or t_host.lower() in ("localhost", "localhost.localdomain"):
            raise HTTPException(status_code=422, detail="token_url must be a public https URL")
        try:
            tl = ipaddress.ip_address(t_host.strip("[]"))
            if not hc.ip_allowed(str(tl), pol):
                raise HTTPException(status_code=422, detail="token_url must be a public https URL")
        except ValueError:
            pass
    if body.auth_type == "basic" and body.secret and ":" not in body.secret:
        raise HTTPException(status_code=422, detail="basic authentication needs the secret as user:password")
    try:
        rules = mapping.validate_rules(body.mapping, [a.key for a in profile_catalog.catalog(db)])
        rest = adapters.validate_rest_config(body.rest_config) if body.kind == "rest" else None
    except (mapping.MappingError, ValueError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    if body.kind == "rest" and rest is None:
        raise HTTPException(status_code=422, detail="a REST application needs rest_config")
    return {"url": url.rstrip("/"), "rules": rules, "rest": rest}


def _dict(db: Session, a: ProvisioningApp) -> dict:
    cnt = lambda q: q.scalar() or 0  # noqa: E731
    return {
        "id": a.id, "public_id": a.public_id, "name": a.name, "description": a.description, "kind": a.kind,
        "base_url": a.base_url, "auth_type": a.auth_type, "header_name": a.header_name, "token_url": a.token_url, "client_id": a.client_id, "scope": a.scope, "has_secret": True,
        "enabled": a.enabled, "options": service.options_of(a), "mapping": a.mapping or [], "rest_config": a.rest_config,
        "last_test": {"at": a.last_test_at.isoformat() if a.last_test_at else None, "ok": a.last_test_ok, "message": a.last_test_message},
        "assigned_users": cnt(db.query(func.count(ProvisioningAssignment.id)).filter(ProvisioningAssignment.app_id == a.id, ProvisioningAssignment.user_id.is_not(None))),
        "assigned_groups": cnt(db.query(func.count(ProvisioningAssignment.id)).filter(ProvisioningAssignment.app_id == a.id, ProvisioningAssignment.group_id.is_not(None))),
        "provisioned": cnt(db.query(func.count(ProvisioningLink.id)).filter(ProvisioningLink.app_id == a.id, ProvisioningLink.resource_type == "user", ProvisioningLink.state == "synced")),
        "errors": cnt(db.query(func.count(ProvisioningLink.id)).filter(ProvisioningLink.app_id == a.id, ProvisioningLink.state == "error")),
        "queued": cnt(db.query(func.count(ProvisioningTask.id)).filter(ProvisioningTask.app_id == a.id, ProvisioningTask.status.in_(("queued", "running")))),
        "failed_tasks": cnt(db.query(func.count(ProvisioningTask.id)).filter(ProvisioningTask.app_id == a.id, ProvisioningTask.status == "failed")),
        "created_at": a.created_at.isoformat(), "updated_at": a.updated_at.isoformat(),
    }


def _get(db: Session, app_id: int) -> ProvisioningApp:
    a = db.get(ProvisioningApp, app_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return a


# ---- catalogue ------------------------------------------------------------------------------------------------

@router.get("/presets")
def presets(_: User = Depends(require_admin)):
    return {"items": PRESETS, "rest_operations": list(adapters.REST_OPS),
            "available": crypto.available()}


@router.get("/mapping")
def mapping_info(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    keys = [a.key for a in profile_catalog.catalog(db)]
    return {"defaults": mapping.default_rules(), "sources": mapping.source_fields(keys)}


# ---- apps -------------------------------------------------------------------------------------------------------

@router.get("")
def list_apps(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return {"items": [_dict(db, a) for a in db.query(ProvisioningApp).order_by(ProvisioningApp.name).all()]}


@router.post("", status_code=201)
def create_app(body: AppBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(_super)):
    _need_key()
    if not body.secret:
        raise HTTPException(status_code=422, detail="secret is required")
    if db.query(func.count(ProvisioningApp.id)).scalar() >= MAX_APPS:
        raise HTTPException(status_code=409, detail=f"At most {MAX_APPS} applications")
    ck = _checked(db, body)
    a = ProvisioningApp(
        public_id=str(uuid.uuid4()), name=body.name.strip(), description=body.description, kind=body.kind, base_url=ck["url"],
        auth_type=body.auth_type, header_name=body.header_name if body.auth_type == "header" else None,
        secret_enc=crypto.encrypt(body.secret), enabled=False, token_url=body.token_url if body.auth_type == "oauth2" else None,
        client_id=body.client_id if body.auth_type == "oauth2" else None, scope=(body.scope or None) if body.auth_type == "oauth2" else None, options=body.options.model_dump(), mapping=ck["rules"],
        rest_config=ck["rest"], created_by=actor.id)
    db.add(a)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Application name already in use")
    record(db, AuditAction.PROVISIONING_APP_CREATED, request, actor, a.id, "provisioning_app", {"name": a.name, "kind": a.kind, "host": urlsplit(a.base_url).hostname})
    db.commit()
    return _dict(db, a)


@router.get("/{app_id}")
def get_app(app_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return _dict(db, _get(db, app_id))


@router.put("/{app_id}")
def update_app(app_id: int, body: AppBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(_super)):
    a = _get(db, app_id)
    _need_key()
    ck = _checked(db, body)
    oa = body.auth_type == "oauth2"
    new_oauth = (body.token_url if oa else None, body.client_id if oa else None, (body.scope or None) if oa else None)
    connection_changed = ((ck["url"], body.auth_type, body.header_name, body.kind) != (a.base_url, a.auth_type, a.header_name, a.kind)
                          or new_oauth != (a.token_url, a.client_id, a.scope) or bool(body.secret))
    behaviour_changed = (body.options.model_dump(), ck["rules"], ck["rest"]) != (service.options_of(a), a.mapping or [], a.rest_config)
    a.name, a.description, a.kind, a.base_url, a.auth_type = body.name.strip(), body.description, body.kind, ck["url"], body.auth_type
    a.header_name = body.header_name if body.auth_type == "header" else None
    a.token_url, a.client_id, a.scope = new_oauth
    a.options, a.mapping, a.rest_config = body.options.model_dump(), ck["rules"], ck["rest"]
    if body.secret:
        a.secret_enc = crypto.encrypt(body.secret)
    if connection_changed:
        a.last_test_ok, a.last_test_at, a.last_test_message = None, None, None
        if a.enabled:
            a.enabled = False  # a changed destination or credential must be tested again before anything is sent
    want = body.enabled if body.enabled is not None else a.enabled
    if want and not a.enabled:
        if a.last_test_ok is not True:
            raise HTTPException(status_code=409, detail="Test the connection successfully before enabling this application")
        a.enabled = True
        behaviour_changed = True
    elif body.enabled is False:
        a.enabled = False
    a.updated_at = datetime.now(timezone.utc)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Application name already in use")
    queued = service.queue_full_sync(db, a) if (a.enabled and behaviour_changed) else None
    record(db, AuditAction.PROVISIONING_APP_UPDATED, request, actor, a.id, "provisioning_app",
           {"name": a.name, "enabled": a.enabled, "secret_rotated": bool(body.secret), "connection_changed": connection_changed})
    db.commit()
    return {**_dict(db, a), "queued": queued}


@router.delete("/{app_id}")
def delete_app(app_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(_super)):
    a = _get(db, app_id)
    name = a.name
    db.delete(a)
    record(db, AuditAction.PROVISIONING_APP_DELETED, request, actor, app_id, "provisioning_app",
           {"name": name, "note": "accounts already created in the application are left as they are"})
    db.commit()
    return {"success": True}


@router.post("/{app_id}/test")
def test_app(app_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(_super)):
    a = _get(db, app_id)
    _need_key()
    try:
        message, ok = adapters.build(a, crypto.decrypt(a.secret_enc)).test(), True
    except (adapters.Permanent, adapters.Retryable) as e:
        message, ok = str(e)[:300], False
    except crypto.RecipeKeyError as e:
        message, ok = str(e)[:300], False
    a.last_test_at, a.last_test_ok, a.last_test_message = datetime.now(timezone.utc), ok, message[:300]
    record(db, AuditAction.PROVISIONING_APP_TESTED, request, actor, a.id, "provisioning_app", {"ok": ok})
    db.commit()
    return {"ok": ok, "message": message}


@router.post("/{app_id}/sync")
def sync_app(app_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(_super)):
    a = _get(db, app_id)
    if not a.enabled:
        raise HTTPException(status_code=409, detail="Enable the application first")
    queued = service.queue_full_sync(db, a)
    record(db, AuditAction.PROVISIONING_SYNC_REQUESTED, request, actor, a.id, "provisioning_app", queued)
    db.commit()
    return {"queued": queued}


@router.post("/{app_id}/deprovision-all")
def deprovision_all(app_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(_super)):
    """Remove every assignment and queue the work: each provisioned account is deactivated/deleted per the app's policy.
    Keep the app turned on until the queue is empty; delete it afterwards."""
    a = _get(db, app_id)
    if not a.enabled:
        raise HTTPException(status_code=409, detail="Turn the application on first so the changes can be sent")
    removed = db.query(ProvisioningAssignment).filter(ProvisioningAssignment.app_id == a.id).delete(synchronize_session=False)
    db.flush()
    queued = service.queue_full_sync(db, a)
    record(db, AuditAction.PROVISIONING_SYNC_REQUESTED, request, actor, a.id, "provisioning_app", {**queued, "deprovision_all": True, "assignments_removed": removed})
    db.commit()
    return {"assignments_removed": removed, "queued": queued}


@router.get("/{app_id}/preview")
def preview(app_id: int, user_id: int = Query(...), db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """What would be sent for this user (the canonical SCIM resource; a gateway maps it into the app's own JSON)."""
    a = _get(db, app_id)
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="User not found")
    return {"entitled": service.is_entitled(db, a, u.id), "resource": mapping.user_resource(u, a, active=u.status == "active")}


# ---- assignments --------------------------------------------------------------------------------------------------

class AssignBody(BaseModel):
    user_id: Optional[int] = None
    group_id: Optional[int] = None


def _assignment_dict(db: Session, x: ProvisioningAssignment) -> dict:
    if x.user_id:
        u = db.get(User, x.user_id)
        return {"id": x.id, "type": "user", "subject_id": x.user_id, "name": f"{u.first_name} {u.last_name}".strip() if u else "", "detail": u.email if u else ""}
    g = db.get(Group, x.group_id)
    return {"id": x.id, "type": "group", "subject_id": x.group_id, "name": g.name if g else "", "detail": "all members"}


@router.get("/{app_id}/assignments")
def list_assignments(app_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    _get(db, app_id)
    rows = db.query(ProvisioningAssignment).filter(ProvisioningAssignment.app_id == app_id).order_by(ProvisioningAssignment.id).limit(500).all()
    return {"items": [_assignment_dict(db, x) for x in rows]}


@router.post("/{app_id}/assignments", status_code=201)
def add_assignment(app_id: int, body: AssignBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    a = _get(db, app_id)
    if (body.user_id is None) == (body.group_id is None):
        raise HTTPException(status_code=422, detail="Give either user_id or group_id")
    if body.user_id is not None and db.get(User, body.user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    if body.group_id is not None and db.get(Group, body.group_id) is None:
        raise HTTPException(status_code=404, detail="Group not found")
    x = ProvisioningAssignment(app_id=a.id, user_id=body.user_id, group_id=body.group_id, created_by=actor.id)
    db.add(x)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Already assigned")
    if a.enabled:
        if body.user_id is not None:
            service.queue_user(db, body.user_id, [a])
        else:
            for uid in service.group_members(db, body.group_id):
                service.queue(db, a.id, "user", user_id=uid)
            if service.options_of(a)["push_groups"]:
                service.queue(db, a.id, "group", group_id=body.group_id)
    record(db, AuditAction.PROVISIONING_ASSIGNMENT_ADDED, request, actor, a.id, "provisioning_app",
           {"user_id": body.user_id, "group_id": body.group_id})
    db.commit()
    return _assignment_dict(db, x)


@router.delete("/{app_id}/assignments/{assignment_id}")
def remove_assignment(app_id: int, assignment_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    a = _get(db, app_id)
    x = db.get(ProvisioningAssignment, assignment_id)
    if x is None or x.app_id != a.id:
        raise HTTPException(status_code=404, detail="Assignment not found")
    affected = [x.user_id] if x.user_id is not None else service.group_members(db, x.group_id)
    gid, uid = x.group_id, x.user_id
    db.delete(x)
    db.flush()
    if a.enabled:
        for u in affected:
            service.queue(db, a.id, "user", user_id=u)  # the worker re-evaluates: still entitled elsewhere, or deprovision
        if gid is not None and service.options_of(a)["push_groups"]:
            service.queue(db, a.id, "group", group_id=gid)
    record(db, AuditAction.PROVISIONING_ASSIGNMENT_REMOVED, request, actor, a.id, "provisioning_app", {"user_id": uid, "group_id": gid})
    db.commit()
    return {"success": True}


# ---- activity -----------------------------------------------------------------------------------------------------

@router.get("/{app_id}/links")
def list_links(app_id: int, state: Optional[str] = Query(None, pattern="^(synced|deprovisioned|error)$"), q: str = Query("", max_length=100),
               limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), db: Session = Depends(get_db), _: User = Depends(require_admin)):
    _get(db, app_id)
    query = db.query(ProvisioningLink).filter(ProvisioningLink.app_id == app_id)
    if state:
        query = query.filter(ProvisioningLink.state == state)
    if q.strip():
        like = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.filter(ProvisioningLink.label.ilike(like, escape="\\"))
    total = query.count()
    rows = query.order_by(ProvisioningLink.id.desc()).offset(offset).limit(limit).all()
    return {"total": total, "items": [{
        "id": r.id, "type": r.resource_type, "user_id": r.user_id, "group_id": r.group_id, "label": r.label, "remote_id": r.remote_id,
        "state": r.state, "last_error": r.last_error, "last_synced_at": r.last_synced_at.isoformat() if r.last_synced_at else None} for r in rows]}


@router.get("/{app_id}/tasks")
def list_tasks(app_id: int, status: Optional[str] = Query(None, pattern="^(queued|running|succeeded|failed)$"),
               db: Session = Depends(get_db), _: User = Depends(require_admin)):
    _get(db, app_id)
    q = db.query(ProvisioningTask).filter(ProvisioningTask.app_id == app_id)
    if status:
        q = q.filter(ProvisioningTask.status == status)
    rows = q.order_by(ProvisioningTask.id.desc()).limit(100).all()
    return {"items": [{
        "id": t.id, "resource_type": t.resource_type, "user_id": t.user_id, "group_id": t.group_id, "op": t.op, "status": t.status,
        "attempts": t.attempts, "result": t.result, "last_error": t.last_error, "created_at": t.created_at.isoformat(),
        "finished_at": t.finished_at.isoformat() if t.finished_at else None} for t in rows]}


@router.post("/{app_id}/tasks/{task_id}/retry")
def retry_task(app_id: int, task_id: int, db: Session = Depends(get_db), _: User = Depends(_super)):
    _get(db, app_id)
    t = db.get(ProvisioningTask, task_id)
    if t is None or t.app_id != app_id:
        raise HTTPException(status_code=404, detail="Task not found")
    if t.status != "failed":
        raise HTTPException(status_code=409, detail="Only failed tasks can be retried")
    t.status, t.attempts, t.last_error, t.next_run_at, t.finished_at = "queued", 0, None, datetime.now(timezone.utc), None
    db.commit()
    return {"success": True}
