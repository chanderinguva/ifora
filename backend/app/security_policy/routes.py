"""Organization security policy API: admin read/write, plus the public password rules shown beside password fields."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.auth.deps import require_admin
from backend.app.db import get_db
from backend.app.security_policy import service as svc
from backend.app.security_policy.models import OrgSecurityPolicy
from backend.app.users.model import User

router = APIRouter(prefix="/admin/security-policy", tags=["security-policy"])
public_router = APIRouter(tags=["security-policy"])


class PolicyBody(BaseModel):
    min_length: int = Field(..., ge=8, le=64)
    require_mixed_case: bool
    require_digit: bool
    require_symbol: bool
    no_user_info: bool
    history_count: int = Field(..., ge=0, le=24)
    max_age_days: int = Field(..., ge=0, le=730)
    max_failed_attempts: int = Field(..., ge=3, le=20)
    lockout_minutes: int = Field(..., ge=1, le=1440)
    session_lifetime_hours: int = Field(..., ge=1, le=168)
    idle_timeout_minutes: int = Field(..., ge=5, le=1440)
    email_otp_members: Optional[str] = Field(None, pattern="^(off|allowed)$")  # omitted = keep the current value
    email_otp_admins: Optional[str] = Field(None, pattern="^(off|allowed|required)$")
    push_members: Optional[str] = Field(None, pattern="^(off|allowed)$")
    push_admins: Optional[str] = Field(None, pattern="^(off|allowed|required)$")


def _would_expire(db: Session, p: svc.Policy) -> int:
    """Active users whose password is already older than the saved maximum age; they must change it at next sign-in."""
    if not p.max_age_days:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=p.max_age_days)
    return db.query(func.count(User.id)).filter(User.status == "active", func.coalesce(User.password_changed_at, User.created_at) < cutoff).scalar() or 0


def _out(db: Session, p: svc.Policy) -> dict:
    return {"policy": p.as_dict(), "defaults": svc.defaults().as_dict(), "rules": svc.rules(p), "users_past_max_age": _would_expire(db, p)}


@router.get("")
def read_policy(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return _out(db, svc.get(db))


@router.put("")
def write_policy(body: PolicyBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    if body.idle_timeout_minutes > body.session_lifetime_hours * 60:
        raise HTTPException(status_code=422, detail="The idle timeout cannot be longer than the session lifetime")
    if body.email_otp_admins == "required":
        from backend.app import mailer

        if not mailer.configured():
            raise HTTPException(status_code=422, detail="Set up outgoing email before requiring email codes")
    if body.push_admins == "required":
        from backend.app.auth import push_mfa

        if not push_mfa.configured():
            raise HTTPException(status_code=422, detail="Set up push notifications (VAPID keys) before requiring them")
    before = svc.get(db)
    values = {k: v for k, v in body.model_dump().items() if v is not None}
    values = {**before.as_dict(), **values}
    row = db.query(OrgSecurityPolicy).first()
    if row is None:
        row = OrgSecurityPolicy(**values)
        db.add(row)
    else:
        for k, v in values.items():
            setattr(row, k, v)
    row.updated_by, row.updated_at = actor.id, datetime.now(timezone.utc)
    after = svc.Policy(**values)
    changed = {k: [v, getattr(after, k)] for k, v in before.as_dict().items() if getattr(after, k) != v}
    record(db, AuditAction.SECURITY_POLICY_CHANGED, request, actor, None, "security_policy", {"changed": changed})
    db.commit()
    return _out(db, after)


@public_router.get("/password-policy")
def password_policy(response: Response, db: Session = Depends(get_db)):
    """Unauthenticated: the rules a new password must meet (so the set-password page can show them). No other settings."""
    response.headers["Cache-Control"] = "no-cache"
    p = svc.get(db)
    return {"rules": svc.rules(p), "min_length": p.min_length}
