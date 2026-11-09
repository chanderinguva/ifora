"""Self-service access requests (ADR 017): ask for an app, an administrator approves or denies.

Approval creates an ordinary direct assignment, so entitlement, provisioning and audit all behave exactly as if an
administrator had assigned the user by hand. Nothing here widens what an unassigned user can see or launch.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.access_requests.models import AccessRequest, AppSelfService
from backend.app.applications import entitlement as ent
from backend.app.applications.models import Application, ApplicationAssignment, ApplicationIcon
from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.auth.deps import get_current_user, require_admin
from backend.app.db import get_db
from backend.app.users.model import User

me_router = APIRouter(prefix="/me/access", tags=["access-requests"])
admin_router = APIRouter(prefix="/admin/access-requests", tags=["access-requests"])
settings_router = APIRouter(prefix="/admin/applications", tags=["access-requests"])
MAX_PENDING = 20


def _cfg(db: Session, app_id: int) -> Optional[AppSelfService]:
    return db.get(AppSelfService, app_id)


def _requestable(db: Session, a: Optional[Application]) -> bool:
    if a is None or a.status != "active" or not a.visible or a.sign_on_mode == "none":
        return False
    c = _cfg(db, a.id)
    return bool(c and c.enabled)


def _text(v: Optional[str]) -> Optional[str]:
    v = (v or "").strip()
    if any(ord(c) < 32 and c not in "\n\t" for c in v):
        raise HTTPException(status_code=422, detail="Text contains control characters")
    return v or None


def _row(db: Session, r: AccessRequest, admin_view: bool = False) -> dict:
    a, u = db.get(Application, r.application_id), db.get(User, r.user_id)
    d = {"id": r.id, "application_id": r.application_id, "application_name": a.name if a else "(deleted)", "reason": r.reason, "status": r.status,
         "decision_note": r.decision_note, "created_at": r.created_at.isoformat(), "decided_at": r.decided_at.isoformat() if r.decided_at else None}
    if admin_view:
        by = db.get(User, r.decided_by) if r.decided_by else None
        d.update({"user_id": r.user_id, "user_email": u.email if u else None, "user_name": f"{u.first_name} {u.last_name}" if u else None,
                  "decided_by_email": by.email if by else None})
    return d


# ---- end user -------------------------------------------------------------------------------------------------------

@me_router.get("/catalog")
def catalog(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Applications the user may ask for: self-service on, active, visible, and not already theirs."""
    enabled = [c.application_id for c in db.query(AppSelfService).filter(AppSelfService.enabled.is_(True)).all()]
    mine = ent.entitled_application_ids(db, user.id)
    ids = [i for i in enabled if i not in mine]
    apps = db.query(Application).filter(Application.id.in_(ids or [0]), Application.status == "active", Application.visible.is_(True),
                                        Application.sign_on_mode != "none").order_by(Application.name).all()
    pending = {a for (a,) in db.query(AccessRequest.application_id).filter(AccessRequest.user_id == user.id, AccessRequest.status == "pending").all()}
    icons = {i for (i,) in db.query(ApplicationIcon.application_id).filter(ApplicationIcon.application_id.in_([a.id for a in apps] or [0])).all()}
    return {"items": [{"id": a.id, "name": a.name, "description": a.description, "has_icon": a.id in icons, "pending": a.id in pending,
                       "reason_required": bool((_cfg(db, a.id) or AppSelfService(reason_required=False)).reason_required)} for a in apps]}


@me_router.get("/catalog/{app_id}/icon")
def catalog_icon(app_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from backend.app.applications.routes import _icon_response

    a = db.get(Application, app_id)
    icon = db.get(ApplicationIcon, app_id) if a is not None else None
    if icon is None or not _requestable(db, a):
        raise HTTPException(status_code=404, detail="Not found")
    return _icon_response(icon)


class RequestBody(BaseModel):
    application_id: int
    reason: Optional[str] = Field(None, max_length=500)


@me_router.post("/requests", status_code=201)
def create_request(body: RequestBody, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    a = db.get(Application, body.application_id)
    if not _requestable(db, a):
        raise HTTPException(status_code=404, detail="Application not found")  # same answer for missing, off and not requestable
    if ent.is_entitled(db, a.id, user.id):
        raise HTTPException(status_code=409, detail="You already have access to this application")
    reason = _text(body.reason)
    if _cfg(db, a.id).reason_required and not reason:
        raise HTTPException(status_code=422, detail="Please say why you need access")
    if db.query(AccessRequest).filter(AccessRequest.user_id == user.id, AccessRequest.status == "pending").count() >= MAX_PENDING:
        raise HTTPException(status_code=409, detail="You have too many pending requests")
    r = AccessRequest(user_id=user.id, application_id=a.id, reason=reason, status="pending")
    db.add(r)
    record(db, AuditAction.ACCESS_REQUESTED, request, user, a.id, "application", {"name": a.name})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="You already have a pending request for this application")
    return _row(db, r)


@me_router.get("/requests")
def my_requests(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(AccessRequest).filter(AccessRequest.user_id == user.id).order_by(AccessRequest.id.desc()).limit(50).all()
    return {"items": [_row(db, r) for r in rows]}


@me_router.post("/requests/{request_id}/cancel")
def cancel_request(request_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    r = db.query(AccessRequest).filter(AccessRequest.id == request_id).with_for_update().first()
    if r is None or r.user_id != user.id:
        raise HTTPException(status_code=404, detail="Request not found")
    if r.status != "pending":
        raise HTTPException(status_code=409, detail="Only a pending request can be canceled")
    r.status, r.decided_at = "canceled", datetime.now(timezone.utc)
    record(db, AuditAction.ACCESS_REQUEST_CANCELED, request, user, r.application_id, "application", {"request_id": r.id})
    db.commit()
    return _row(db, r)


# ---- administrators -------------------------------------------------------------------------------------------------

@admin_router.get("")
def list_requests(status: str = Query("pending", pattern="^(pending|approved|denied|canceled|all)$"), db: Session = Depends(get_db), _: User = Depends(require_admin)):
    q = db.query(AccessRequest)
    if status != "all":
        q = q.filter(AccessRequest.status == status)
    rows = q.order_by(AccessRequest.id.desc()).limit(200).all()
    return {"items": [_row(db, r, True) for r in rows]}


class DecideBody(BaseModel):
    note: Optional[str] = Field(None, max_length=500)


def _locked_pending(db: Session, request_id: int, actor: User) -> AccessRequest:
    r = db.query(AccessRequest).filter(AccessRequest.id == request_id).with_for_update().first()
    if r is None:
        raise HTTPException(status_code=404, detail="Request not found")
    if r.user_id == actor.id:
        raise HTTPException(status_code=403, detail="You cannot decide your own request")  # separation of duties
    if r.status != "pending":
        raise HTTPException(status_code=409, detail="This request has already been decided")
    return r


@admin_router.post("/{request_id}/approve")
def approve(request_id: int, body: DecideBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    from backend.app.provisioning import service as prov

    r = _locked_pending(db, request_id, actor)
    a, u = db.get(Application, r.application_id), db.get(User, r.user_id)
    if a is None or a.status != "active":
        raise HTTPException(status_code=409, detail="The application is not active")
    if u is None or u.status != "active":
        raise HTTPException(status_code=409, detail="The user is not active")
    if not ent.is_entitled(db, a.id, u.id):
        db.add(ApplicationAssignment(application_id=a.id, user_id=u.id, created_by=actor.id))
        db.flush()
        prov.on_assignment_change(db, a.id, [u.id], None)
        record(db, AuditAction.APPLICATION_ASSIGNMENT_ADDED, request, actor, a.id, "application", {"user_id": u.id, "group_id": None, "via": "access_request"})
    r.status, r.decided_by, r.decided_at, r.decision_note = "approved", actor.id, datetime.now(timezone.utc), _text(body.note)
    record(db, AuditAction.ACCESS_REQUEST_APPROVED, request, actor, a.id, "application", {"request_id": r.id, "user_id": u.id})
    db.commit()
    return _row(db, r, True)


@admin_router.post("/{request_id}/deny")
def deny(request_id: int, body: DecideBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    r = _locked_pending(db, request_id, actor)
    r.status, r.decided_by, r.decided_at, r.decision_note = "denied", actor.id, datetime.now(timezone.utc), _text(body.note)
    record(db, AuditAction.ACCESS_REQUEST_DENIED, request, actor, r.application_id, "application", {"request_id": r.id, "user_id": r.user_id})
    db.commit()
    return _row(db, r, True)


# ---- per-application switch (admin, applications area) -------------------------------------------------------------

class SelfServiceBody(BaseModel):
    enabled: bool
    reason_required: bool = False


@settings_router.get("/{app_id}/self-service")
def get_self_service(app_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    if db.get(Application, app_id) is None:
        raise HTTPException(status_code=404, detail="Application not found")
    c = _cfg(db, app_id)
    return {"enabled": bool(c and c.enabled), "reason_required": bool(c and c.reason_required)}


@settings_router.put("/{app_id}/self-service")
def put_self_service(app_id: int, body: SelfServiceBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    a = db.get(Application, app_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Application not found")
    c = _cfg(db, app_id)
    if c is None:
        c = AppSelfService(application_id=app_id)
        db.add(c)
    c.enabled, c.reason_required, c.updated_at = body.enabled, body.reason_required, datetime.now(timezone.utc)
    record(db, AuditAction.APPLICATION_SELF_SERVICE_CHANGED, request, actor, a.id, "application", {"enabled": body.enabled, "reason_required": body.reason_required})
    db.commit()
    return {"enabled": c.enabled, "reason_required": c.reason_required}
