"""Access request lifecycle rules (IFORA-37): who may decide a stage, SoD conflicts, granting, expiry and escalation.

Granting and removing reuse the exact assignment path administrators use (`ApplicationAssignment` + provisioning hooks + audit), so
entitlement, provisioning and the audit trail behave as if an administrator had done it by hand.
"""

from datetime import datetime, timedelta, timezone
from typing import List, Optional, Set

import structlog
from sqlalchemy.orm import Session

from backend.app import mailer
from backend.app.access_requests.models import AccessRequest, AccessRequestDecision, ApprovalPolicy, ApprovalStage, SodRule
from backend.app.applications import entitlement as ent
from backend.app.applications.models import Application, ApplicationAssignment
from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.groups.model import Group
from backend.app.users.model import User

logger = structlog.get_logger(__name__)
MAX_STAGES = 3


def policy(db: Session, app_id: int) -> Optional[ApprovalPolicy]:
    return db.get(ApprovalPolicy, app_id)


def stages(db: Session, app_id: int) -> List[ApprovalStage]:
    return db.query(ApprovalStage).filter(ApprovalStage.application_id == app_id).order_by(ApprovalStage.position).all()


def durations(db: Session, app_id: int) -> List[int]:
    p = policy(db, app_id)
    return sorted({int(d) for d in (p.durations or [])}) if p else []


def manager_of(db: Session, user: User) -> Optional[User]:
    """The requester's manager from the profile attributes `manager` (an email address) or `manager_id` (an email address or a user id)."""
    attrs = user.get_profile_attributes() or {}
    for key in ("manager", "manager_id"):
        v = str(attrs.get(key) or "").strip()
        if not v:
            continue
        m = db.query(User).filter(User.email == v.lower()).first() if "@" in v else (db.get(User, int(v)) if v.isdigit() else None)
        if m is not None and m.id != user.id and m.status == "active":
            return m
    return None


def approver_ids(db: Session, r: AccessRequest, stage: int) -> Set[int]:
    """Users who may decide `stage` of this request, before the separation-of-duties exclusions."""
    row = next((s for s in stages(db, r.application_id) if s.position == stage), None)
    if row is None:
        return set()
    if row.approver_kind == "owner":
        a = db.get(Application, r.application_id)
        return {a.owner_user_id} if a is not None and a.owner_user_id else set()
    if row.approver_kind == "manager":
        u = db.get(User, r.user_id)
        m = manager_of(db, u) if u is not None else None
        return {m.id} if m else set()
    from backend.app.provisioning import service as prov

    return {i for i in prov.group_members(db, row.group_id)}


def previous_deciders(db: Session, r: AccessRequest) -> Set[int]:
    return {d for (d,) in db.query(AccessRequestDecision.decided_by).filter(AccessRequestDecision.request_id == r.id).all() if d is not None}


def sod_conflicts(db: Session, user_id: int, app_id: int) -> List[Application]:
    """Applications the user already holds that an SoD rule pairs with `app_id`."""
    rules = db.query(SodRule).filter((SodRule.app_a_id == app_id) | (SodRule.app_b_id == app_id)).all()
    if not rules:
        return []
    others = {r.app_b_id if r.app_a_id == app_id else r.app_a_id for r in rules}
    held = others & ent.entitled_application_ids(db, user_id)
    return db.query(Application).filter(Application.id.in_(held or [0])).order_by(Application.name).all()


def grant(db: Session, r: AccessRequest, a: Application, u: User, actor: Optional[User], request=None) -> None:
    """Final approval: the ordinary direct assignment, with the expiry the requester asked for."""
    from backend.app.provisioning import service as prov

    if not ent.is_entitled(db, a.id, u.id):
        db.add(ApplicationAssignment(application_id=a.id, user_id=u.id, created_by=actor.id if actor else None))
        db.flush()
        prov.on_assignment_change(db, a.id, [u.id], None)
        record(db, AuditAction.APPLICATION_ASSIGNMENT_ADDED, request, actor, a.id, "application", {"user_id": u.id, "group_id": None, "via": "access_request"})
    r.expires_at = datetime.now(timezone.utc) + timedelta(days=r.duration_days) if r.duration_days else None


def expire_due(db: Session, now: Optional[datetime] = None) -> int:
    """Remove the grants whose time is up. Idempotent: a row leaves the 'approved' state once handled, and a missing assignment is fine."""
    from backend.app.provisioning import service as prov

    now = now or datetime.now(timezone.utc)
    rows = (db.query(AccessRequest).filter(AccessRequest.status == "approved", AccessRequest.expires_at.is_not(None), AccessRequest.expires_at <= now)
            .order_by(AccessRequest.id).with_for_update(skip_locked=True).limit(200).all())
    for r in rows:
        x = db.query(ApplicationAssignment).filter(ApplicationAssignment.application_id == r.application_id, ApplicationAssignment.user_id == r.user_id).first()
        if x is not None:
            db.delete(x)
            db.flush()
            prov.on_assignment_change(db, r.application_id, [r.user_id], None)
            record(db, AuditAction.APPLICATION_ASSIGNMENT_REMOVED, None, None, r.application_id, "application", {"user_id": r.user_id, "group_id": None, "via": "access_request_expiry"})
        r.status = "expired"
        record(db, AuditAction.ACCESS_REQUEST_EXPIRED, None, None, r.application_id, "application", {"request_id": r.id, "user_id": r.user_id})
    db.commit()
    return len(rows)


def _mail(to: Optional[str], subject: str, body: str) -> None:
    if not to or not mailer.configured():
        return
    try:
        mailer.send(mailer.build(to, subject, body), timeout=10)
    except Exception as e:  # noqa: BLE001 - a mail failure never blocks the lifecycle; the message text stays out of the log
        logger.warning("access_request.mail_failed", error=type(e).__name__)


def escalate_due(db: Session, now: Optional[datetime] = None) -> int:
    """One reminder to the current stage's approvers for requests pending past the app's timeout; the request is marked escalated so it
    is never reminded twice."""
    now = now or datetime.now(timezone.utc)
    sent = 0
    rows = (db.query(AccessRequest).join(ApprovalPolicy, ApprovalPolicy.application_id == AccessRequest.application_id)
            .filter(AccessRequest.status == "pending", AccessRequest.escalated_at.is_(None), ApprovalPolicy.timeout_hours.is_not(None))
            .order_by(AccessRequest.id).with_for_update(skip_locked=True, of=AccessRequest).limit(200).all())
    for r in rows:
        p = policy(db, r.application_id)
        if r.created_at + timedelta(hours=p.timeout_hours) > now:
            continue
        a, u = db.get(Application, r.application_id), db.get(User, r.user_id)
        ids = approver_ids(db, r, r.stage) if r.routed else set()
        to = [x.email for x in db.query(User).filter(User.id.in_(ids or [0]), User.status == "active").all()]
        if not r.routed:  # un-routed requests are decided by administrators
            to = [x.email for x in db.query(User).filter(User.is_admin.is_(True), User.status == "active").limit(20).all()]
        for addr in to:
            _mail(addr, f"Access request waiting: {a.name if a else 'application'}",
                  f"{u.email if u else 'A user'} asked for access to {a.name if a else 'an application'} and is still waiting for a decision. Open Ifora to approve or deny it.")
            sent += 1
        r.escalated_at = now
        record(db, AuditAction.ACCESS_REQUEST_ESCALATED, None, None, r.application_id, "application", {"request_id": r.id, "reminded": len(to)})
    db.commit()
    return sent
