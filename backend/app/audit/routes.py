"""Admin audit log and dashboard statistics."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.app.audit.model import AuditAction, AuditEvent
from backend.app.auth.deps import require_admin
from backend.app.auth.session import Session as AuthSession
from backend.app.auth.session import SessionStatus
from backend.app.db import get_db
from backend.app.groups.model import Group, user_group_association
from backend.app.users.model import User

router = APIRouter(prefix="/admin", tags=["audit"])

_ACTIONS = "^(" + "|".join(a.value for a in AuditAction) + ")$"


def _with_actor_email(db: Session, events):
    ids = {int(e.actor_id) for e in events if e.actor_id and e.actor_id.isdigit()}
    emails = {u.id: u.email for u in db.query(User.id, User.email).filter(User.id.in_(ids))} if ids else {}
    out = []
    for e in events:
        d = e.to_dict()
        d["actor_email"] = emails.get(int(e.actor_id)) if e.actor_id and e.actor_id.isdigit() else None
        out.append(d)
    return out


@router.get("/audit")
def list_audit(
    action: Optional[str] = Query(None, pattern=_ACTIONS),
    actor_id: Optional[int] = Query(None, ge=1),
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    q = db.query(AuditEvent)
    if action:
        q = q.filter(AuditEvent.action == action)
    if actor_id:
        q = q.filter(AuditEvent.actor_id == str(actor_id))
    total = q.count()
    rows = q.order_by(AuditEvent.timestamp.desc(), AuditEvent.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": _with_actor_email(db, rows), "total": total, "page": page, "page_size": page_size}


@router.get("/stats")
def stats(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    now = datetime.now(timezone.utc)
    users_total = db.query(func.count(User.id)).scalar()
    users_active = db.query(func.count(User.id)).filter(User.status == "active").scalar()
    admins = db.query(func.count(User.id)).filter(User.is_admin.is_(True)).scalar()
    groups = db.query(func.count(Group.id)).scalar()
    memberships = db.execute(func.count().select().select_from(user_group_association)).scalar()
    sessions = (
        db.query(func.count(AuthSession.id))
        .filter(AuthSession.status == SessionStatus.ACTIVE.value, AuthSession.expires_at > now)
        .scalar()
    )
    failed_24h = (
        db.query(func.count(AuditEvent.id))
        .filter(AuditEvent.action == AuditAction.LOGIN_FAILURE.value, AuditEvent.timestamp > now - timedelta(hours=24))
        .scalar()
    )
    recent = db.query(AuditEvent).order_by(AuditEvent.timestamp.desc(), AuditEvent.id.desc()).limit(8).all()
    return {
        "users_total": users_total,
        "users_active": users_active,
        "admins": admins,
        "groups": groups,
        "memberships": memberships,
        "active_sessions": sessions,
        "failed_logins_24h": failed_24h,
        "recent_events": _with_actor_email(db, recent),
    }
