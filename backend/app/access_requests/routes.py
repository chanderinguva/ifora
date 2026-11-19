"""Self-service access requests (ADR 017, IFORA-37): ask for an app; the app's approvers (or, without a policy, an administrator) decide.

Approval creates an ordinary direct assignment, so entitlement, provisioning and audit all behave exactly as if an
administrator had assigned the user by hand. Nothing here widens what an unassigned user can see or launch.

Lifecycle (IFORA-37): an application may have an approval policy of 1-3 ordered stages (owner, the requester's manager, or a named
group), allowed grant durations and a pending timeout. Requests made under a policy are `routed` and decided only by that stage's
approvers through /me/approvals; everything else stays decidable by any administrator, as before.
"""

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.access_requests import service as svc
from backend.app.access_requests.models import AccessRequest, AccessRequestDecision, AppSelfService, ApprovalPolicy, ApprovalStage, SodRule
from backend.app.applications import entitlement as ent
from backend.app.applications.models import Application, ApplicationIcon
from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.auth.deps import get_current_user, require_admin
from backend.app.db import get_db
from backend.app.groups.model import Group
from backend.app.users.model import User

me_router = APIRouter(prefix="/me/access", tags=["access-requests"])
approvals_router = APIRouter(prefix="/me/approvals", tags=["access-requests"])
admin_router = APIRouter(prefix="/admin/access-requests", tags=["access-requests"])
settings_router = APIRouter(prefix="/admin/applications", tags=["access-requests"])
MAX_PENDING = 20
MAX_DURATIONS = 6


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


def _iso(v):
    return v.isoformat() if v else None


def _row(db: Session, r: AccessRequest, admin_view: bool = False) -> dict:
    a, u = db.get(Application, r.application_id), db.get(User, r.user_id)
    d = {"id": r.id, "application_id": r.application_id, "application_name": a.name if a else "(deleted)", "reason": r.reason, "status": r.status,
         "decision_note": r.decision_note, "created_at": r.created_at.isoformat(), "decided_at": _iso(r.decided_at),
         "stage": r.stage, "stages_total": r.stages_total, "duration_days": r.duration_days, "expires_at": _iso(r.expires_at),
         "escalated": r.escalated_at is not None, "sod_conflict": r.sod_conflict}
    if admin_view:
        by = db.get(User, r.decided_by) if r.decided_by else None
        d.update({"user_id": r.user_id, "user_email": u.email if u else None, "user_name": f"{u.first_name} {u.last_name}" if u else None,
                  "decided_by_email": by.email if by else None, "routed": r.routed, "exception_reason": r.exception_reason,
                  "sod_apps": [x.name for x in svc.sod_conflicts(db, r.user_id, r.application_id)] if r.status == "pending" else []})
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
                       "reason_required": bool((_cfg(db, a.id) or AppSelfService(reason_required=False)).reason_required),
                       "durations": svc.durations(db, a.id), "stages": len(svc.stages(db, a.id))} for a in apps]}


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
    duration_days: Optional[int] = Field(None, ge=1, le=3650)


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
    allowed = svc.durations(db, a.id)
    if allowed and body.duration_days not in allowed:
        raise HTTPException(status_code=422, detail="Choose how long you need access")
    if not allowed and body.duration_days is not None:
        raise HTTPException(status_code=422, detail="This application does not offer time-limited access")
    st = svc.stages(db, a.id)
    r = AccessRequest(user_id=user.id, application_id=a.id, reason=reason, status="pending", duration_days=body.duration_days,
                      routed=bool(st), stage=1, stages_total=max(len(st), 1))
    if st and not svc.approver_ids(db, r, 1) and not any(svc.approver_ids(db, r, s.position) for s in st):
        raise HTTPException(status_code=409, detail="No approver is available for this application yet; ask an administrator")
    if any(not svc.approver_ids(db, r, s.position) for s in st):
        raise HTTPException(status_code=409, detail="An approver for this application cannot be found (for example no manager is set on your profile)")
    if db.query(AccessRequest).filter(AccessRequest.user_id == user.id, AccessRequest.status == "pending").count() >= MAX_PENDING:
        raise HTTPException(status_code=409, detail="You have too many pending requests")
    r.sod_conflict = bool(svc.sod_conflicts(db, user.id, a.id))
    db.add(r)
    record(db, AuditAction.ACCESS_REQUESTED, request, user, a.id, "application", {"name": a.name, "stages": r.stages_total, "duration_days": r.duration_days, "sod_conflict": r.sod_conflict})
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


# ---- deciding (shared) ------------------------------------------------------------------------------------------------

class DecideBody(BaseModel):
    note: Optional[str] = Field(None, max_length=500)
    exception_reason: Optional[str] = Field(None, max_length=500)  # required to approve a request that conflicts with an SoD rule


def _locked_pending(db: Session, request_id: int) -> AccessRequest:
    r = db.query(AccessRequest).filter(AccessRequest.id == request_id).with_for_update().first()
    if r is None:
        raise HTTPException(status_code=404, detail="Request not found")
    return r


def _refuse(db: Session, request: Request, actor: User, r: AccessRequest, why: str) -> None:
    record(db, AuditAction.ACCESS_REQUEST_DECISION_REFUSED, request, actor, r.application_id, "application", {"request_id": r.id, "reason": why, "stage": r.stage})
    db.commit()  # the refusal itself is evidence: keep it even though the request fails
    raise HTTPException(status_code=403, detail="You cannot decide this request")


def _finish_approval(db: Session, request: Request, actor: User, r: AccessRequest, body: DecideBody, via_stage: Optional[int]) -> None:
    """The last (or only) approval: SoD check, then the ordinary assignment."""
    a, u = db.get(Application, r.application_id), db.get(User, r.user_id)
    if a is None or a.status != "active":
        raise HTTPException(status_code=409, detail="The application is not active")
    if u is None or u.status != "active":
        raise HTTPException(status_code=409, detail="The user is not active")
    conflicts = svc.sod_conflicts(db, u.id, a.id)
    exc = _text(body.exception_reason)
    if conflicts:
        if not exc:
            raise HTTPException(status_code=422, detail="This would give the user conflicting access (" + ", ".join(c.name for c in conflicts) + "). Give an exception reason to approve it anyway.")
        r.exception_reason = exc
        record(db, AuditAction.ACCESS_REQUEST_SOD_EXCEPTION, request, actor, a.id, "application",
               {"request_id": r.id, "user_id": u.id, "conflicts_with": [c.name for c in conflicts], "reason": exc})
    svc.grant(db, r, a, u, actor, request)
    r.status, r.decided_by, r.decided_at, r.decision_note = "approved", actor.id, datetime.now(timezone.utc), _text(body.note)
    record(db, AuditAction.ACCESS_REQUEST_APPROVED, request, actor, a.id, "application", {"request_id": r.id, "user_id": u.id, "duration_days": r.duration_days})


# ---- administrators -------------------------------------------------------------------------------------------------

@admin_router.get("")
def list_requests(status: str = Query("pending", pattern="^(pending|approved|denied|canceled|expired|all)$"), db: Session = Depends(get_db), _: User = Depends(require_admin)):
    q = db.query(AccessRequest)
    if status != "all":
        q = q.filter(AccessRequest.status == status)
    rows = q.order_by(AccessRequest.id.desc()).limit(200).all()
    return {"items": [_row(db, r, True) for r in rows]}


def _admin_decidable(db: Session, request: Request, actor: User, r: AccessRequest) -> None:
    if r.user_id == actor.id:
        raise HTTPException(status_code=403, detail="You cannot decide your own request")  # separation of duties
    if r.status != "pending":
        raise HTTPException(status_code=409, detail="This request has already been decided")
    if r.routed:
        raise HTTPException(status_code=403, detail="This request is decided by the application's approvers")


@admin_router.post("/{request_id}/approve")
def approve(request_id: int, body: DecideBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    r = _locked_pending(db, request_id)
    _admin_decidable(db, request, actor, r)
    _finish_approval(db, request, actor, r, body, None)
    db.commit()
    return _row(db, r, True)


@admin_router.post("/{request_id}/deny")
def deny(request_id: int, body: DecideBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    r = _locked_pending(db, request_id)
    _admin_decidable(db, request, actor, r)
    r.status, r.decided_by, r.decided_at, r.decision_note = "denied", actor.id, datetime.now(timezone.utc), _text(body.note)
    record(db, AuditAction.ACCESS_REQUEST_DENIED, request, actor, r.application_id, "application", {"request_id": r.id, "user_id": r.user_id})
    db.commit()
    return _row(db, r, True)


# ---- approver inbox (any signed-in user the policy names) -------------------------------------------------------------

def _is_stage_approver(db: Session, r: AccessRequest, user: User) -> bool:
    return r.routed and r.status == "pending" and user.id in svc.approver_ids(db, r, r.stage)


@approvals_router.get("")
def inbox(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Pending requests the caller may decide at their current stage. Others are simply absent: no way to enumerate requests."""
    rows = db.query(AccessRequest).filter(AccessRequest.routed.is_(True), AccessRequest.status == "pending").order_by(AccessRequest.id).limit(500).all()
    mine = [r for r in rows if _is_stage_approver(db, r, user)]
    out = []
    for r in mine:
        d = _row(db, r, True)
        d["can_decide"] = r.user_id != user.id and user.id not in svc.previous_deciders(db, r)
        out.append(d)
    return {"items": out}


def _approver_gate(db: Session, request: Request, user: User, request_id: int) -> AccessRequest:
    r = _locked_pending(db, request_id)
    if not _is_stage_approver(db, r, user):
        raise HTTPException(status_code=404, detail="Request not found")  # not an approver: the request does not exist for you
    if r.user_id == user.id:
        _refuse(db, request, user, r, "requester_is_approver")
    if user.id in svc.previous_deciders(db, r):
        _refuse(db, request, user, r, "already_decided_earlier_stage")
    return r


def _record_stage(db: Session, r: AccessRequest, user: User, decision: str, note: Optional[str]) -> None:
    db.add(AccessRequestDecision(request_id=r.id, stage=r.stage, decided_by=user.id, decision=decision, note=note))
    db.flush()


@approvals_router.post("/{request_id}/approve")
def approver_approve(request_id: int, body: DecideBody, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    r = _approver_gate(db, request, user, request_id)
    note = _text(body.note)
    if r.stage < r.stages_total:
        _record_stage(db, r, user, "approved", note)
        record(db, AuditAction.ACCESS_REQUEST_STAGE_APPROVED, request, user, r.application_id, "application", {"request_id": r.id, "stage": r.stage})
        r.stage += 1  # still pending: access is granted only after the final stage
    else:
        _finish_approval(db, request, user, r, body, r.stage)
        _record_stage(db, r, user, "approved", note)
    db.commit()
    return _row(db, r, True)


@approvals_router.post("/{request_id}/deny")
def approver_deny(request_id: int, body: DecideBody, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    r = _approver_gate(db, request, user, request_id)
    note = _text(body.note)
    _record_stage(db, r, user, "denied", note)
    r.status, r.decided_by, r.decided_at, r.decision_note = "denied", user.id, datetime.now(timezone.utc), note
    record(db, AuditAction.ACCESS_REQUEST_DENIED, request, user, r.application_id, "application", {"request_id": r.id, "user_id": r.user_id, "stage": r.stage})
    db.commit()
    return _row(db, r, True)


# ---- per-application switch and approval policy (admin, applications area) -------------------------------------------

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


class StageBody(BaseModel):
    kind: str = Field(..., pattern="^(owner|manager|group)$")
    group_id: Optional[int] = None


class PolicyBody(BaseModel):
    stages: List[StageBody] = Field(default_factory=list, max_length=svc.MAX_STAGES)
    durations: List[int] = Field(default_factory=list, max_length=MAX_DURATIONS)  # days; empty = permanent only
    timeout_hours: Optional[int] = Field(None, ge=1, le=8760)


def _policy_dict(db: Session, app_id: int) -> dict:
    p = svc.policy(db, app_id)
    return {"stages": [{"position": s.position, "kind": s.approver_kind, "group_id": s.group_id,
                        "group_name": (db.get(Group, s.group_id).name if s.group_id and db.get(Group, s.group_id) else None)} for s in svc.stages(db, app_id)],
            "durations": svc.durations(db, app_id), "timeout_hours": p.timeout_hours if p else None}


@settings_router.get("/{app_id}/approval-policy")
def get_policy(app_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    if db.get(Application, app_id) is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return _policy_dict(db, app_id)


@settings_router.put("/{app_id}/approval-policy")
def put_policy(app_id: int, body: PolicyBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    a = db.get(Application, app_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Application not found")
    if any(d < 1 or d > 3650 for d in body.durations) or len(set(body.durations)) != len(body.durations):
        raise HTTPException(status_code=422, detail="Durations are distinct numbers of days between 1 and 3650")
    for s in body.stages:
        if (s.kind == "group") != (s.group_id is not None):
            raise HTTPException(status_code=422, detail="A group stage needs a group, and other stages must not have one")
        if s.group_id is not None and db.get(Group, s.group_id) is None:
            raise HTTPException(status_code=422, detail="Group not found")
        if s.kind == "owner" and a.owner_user_id is None:
            raise HTTPException(status_code=422, detail="Set an owner on the application before using the owner as an approver")
    p = svc.policy(db, app_id)
    if p is None:
        p = ApprovalPolicy(application_id=app_id)
        db.add(p)
    p.durations, p.timeout_hours, p.updated_at = sorted(body.durations), body.timeout_hours, datetime.now(timezone.utc)
    db.query(ApprovalStage).filter(ApprovalStage.application_id == app_id).delete()
    db.flush()
    for i, s in enumerate(body.stages, 1):
        db.add(ApprovalStage(application_id=app_id, position=i, approver_kind=s.kind, group_id=s.group_id))
    record(db, AuditAction.APPROVAL_POLICY_CHANGED, request, actor, a.id, "application",
           {"stages": [s.kind for s in body.stages], "durations": sorted(body.durations), "timeout_hours": body.timeout_hours})
    db.commit()
    return _policy_dict(db, app_id)


# ---- separation of duties rules (admin, applications area) -----------------------------------------------------------

class SodBody(BaseModel):
    app_a_id: int
    app_b_id: int
    note: Optional[str] = Field(None, max_length=200)


def _sod_dict(db: Session, x: SodRule) -> dict:
    a, b = db.get(Application, x.app_a_id), db.get(Application, x.app_b_id)
    return {"id": x.id, "app_a_id": x.app_a_id, "app_a_name": a.name if a else None, "app_b_id": x.app_b_id, "app_b_name": b.name if b else None, "note": x.note}


@admin_router.get("/sod-rules")
def list_sod(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return {"items": [_sod_dict(db, x) for x in db.query(SodRule).order_by(SodRule.id).limit(500).all()]}


@admin_router.post("/sod-rules", status_code=201)
def add_sod(body: SodBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    if body.app_a_id == body.app_b_id:
        raise HTTPException(status_code=422, detail="Pick two different applications")
    for i in (body.app_a_id, body.app_b_id):
        if db.get(Application, i) is None:
            raise HTTPException(status_code=404, detail="Application not found")
    lo, hi = sorted((body.app_a_id, body.app_b_id))
    x = SodRule(app_a_id=lo, app_b_id=hi, note=_text(body.note), created_by=actor.id)
    db.add(x)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="That pair already has a rule")
    record(db, AuditAction.SOD_RULE_CHANGED, request, actor, x.id, "sod_rule", {"added": [lo, hi]})
    db.commit()
    return _sod_dict(db, x)


@admin_router.delete("/sod-rules/{rule_id}")
def delete_sod(rule_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    x = db.get(SodRule, rule_id)
    if x is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    record(db, AuditAction.SOD_RULE_CHANGED, request, actor, x.id, "sod_rule", {"removed": [x.app_a_id, x.app_b_id]})
    db.delete(x)
    db.commit()
    return {"success": True}
