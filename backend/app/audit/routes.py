"""Admin audit log and dashboard statistics."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import String, cast, false, func, or_
from sqlalchemy.orm import Session

from backend.app.audit.model import AuditAction, AuditEvent
from backend.app.audit.service import record
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


def _like(value: str) -> str:
    return "%" + value.lower().replace("\\", "").replace("%", "").replace("_", "") + "%"


def _filtered(
    db: Session, action, actor_id, target_type, target_id, q, since, until,
):
    """One filter for the list and the export, so what you see is what you download."""
    query = db.query(AuditEvent)
    if action:
        query = query.filter(AuditEvent.action == action)
    if actor_id:
        query = query.filter(AuditEvent.actor_id == str(actor_id))
    if target_type:
        query = query.filter(AuditEvent.target_type == target_type)
    if target_id:
        query = query.filter(AuditEvent.target_id == str(target_id))
    if since:
        query = query.filter(AuditEvent.timestamp >= since)
    if until:
        query = query.filter(AuditEvent.timestamp <= until)
    if q:
        like = _like(q)
        emails = [i for (i,) in db.query(User.id).filter(func.lower(User.email).like(like)).limit(200)]
        query = query.filter(or_(
            func.lower(AuditEvent.action).like(like),
            func.lower(cast(AuditEvent.event_metadata, String)).like(like),
            func.lower(func.coalesce(AuditEvent.actor_ip_address, "")).like(like),
            AuditEvent.actor_id.in_([str(i) for i in emails]) if emails else false(),
        ))
    return query


_FILTERS = dict(
    action=Query(None, pattern=_ACTIONS),
    actor_id=Query(None, ge=1),
    target_type=Query(None, max_length=50, pattern="^[a-z_]+$"),
    target_id=Query(None, max_length=255),
    q=Query(None, max_length=100),
    since=Query(None),
    until=Query(None),
)


@router.get("/audit")
def list_audit(
    action: Optional[str] = _FILTERS["action"],
    actor_id: Optional[int] = _FILTERS["actor_id"],
    target_type: Optional[str] = _FILTERS["target_type"],
    target_id: Optional[str] = _FILTERS["target_id"],
    q: Optional[str] = _FILTERS["q"],
    since: Optional[datetime] = _FILTERS["since"],
    until: Optional[datetime] = _FILTERS["until"],
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    query = _filtered(db, action, actor_id, target_type, target_id, q, since, until)
    total = query.count()
    rows = query.order_by(AuditEvent.timestamp.desc(), AuditEvent.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": _with_actor_email(db, rows), "total": total, "page": page, "page_size": page_size}


@router.get("/audit/actions")
def audit_actions(_: User = Depends(require_admin)):
    return {"items": sorted(a.value for a in AuditAction)}


EXPORT_MAX = 10000


def _csv_cell(v) -> str:
    """Neutralise spreadsheet formula injection: audit fields can hold attacker-chosen text."""
    t = "" if v is None else str(v)
    return "'" + t if t[:1] in ("=", "+", "-", "@", "\t", "\r") else t


@router.get("/audit/export")
def export_audit(
    request: Request,
    action: Optional[str] = _FILTERS["action"],
    actor_id: Optional[int] = _FILTERS["actor_id"],
    target_type: Optional[str] = _FILTERS["target_type"],
    target_id: Optional[str] = _FILTERS["target_id"],
    q: Optional[str] = _FILTERS["q"],
    since: Optional[datetime] = _FILTERS["since"],
    until: Optional[datetime] = _FILTERS["until"],
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
):
    """CSV of the filtered events (newest first, at most 10,000). The export itself is audited."""
    import csv
    import io
    import json

    from fastapi.responses import Response

    query = _filtered(db, action, actor_id, target_type, target_id, q, since, until)
    total = query.count()
    rows = _with_actor_email(db, query.order_by(AuditEvent.timestamp.desc(), AuditEvent.id.desc()).limit(EXPORT_MAX).all())
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "timestamp", "actor_id", "actor_email", "actor_ip_address", "action", "target_type", "target_id", "metadata"])
    for e in rows:
        w.writerow([_csv_cell(x) for x in (e["id"], e["timestamp"], e["actor_id"], e["actor_email"], e["actor_ip_address"], e["action"],
                                           e["target_type"], e["target_id"], json.dumps(e["metadata"]) if e["metadata"] else "")])
    record(db, AuditAction.AUDIT_EXPORTED, request, actor, None, "audit", {"rows": len(rows), "matched": total, "filters": {
        k: str(v) for k, v in dict(action=action, actor_id=actor_id, target_type=target_type, target_id=target_id, q=q, since=since, until=until).items() if v}})
    db.commit()
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": 'attachment; filename="audit-log.csv"', "Cache-Control": "no-store", "X-Truncated": "true" if total > EXPORT_MAX else "false"})


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
