"""Admin step-up (IFORA-33): sensitive administrator actions need a recent second-factor proof.

A session proves it in one of two ways, both kept server-side on the session row (nothing the client sends decides it):
signing in with a second factor (`amr` holds "mfa"; `auth_time` is then the proof time) or `POST /me/step-up` with a
current authenticator or recovery code (`stepup_at`). The proof is good for ADMIN_STEPUP_MINUTES.

Sensitive actions (each route carries `Depends(require_stepup)`): network zone create/update/delete; application sign-on
policy save/remove; administrator role assignment (user and group); SCIM token create/rotate/restrict; provisioning
application create/update/delete.

Applies where ADMIN_MFA_REQUIRED is on (the default for deployments): every administrator there has a second factor, since
without one `require_admin` already refuses them. API tokens are exempt because they carry no session factor; they are
issued by an administrator in a browser session and are scoped (and optionally read-only) by that act.
Fails closed: a missing or too-old proof is refused with 403 `stepup_required`, and an unreachable rate-limit store is a 503.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.auth import mfa_service
from backend.app.auth.deps import get_session_and_user, require_admin
from backend.app.auth.mfa_routes import mfa_failed, mfa_guard
from backend.app.config import settings
from backend.app.db import get_db
from backend.app.users.model import User

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["step-up"])
STEPUP_REQUIRED = "stepup_required"


def proof(session) -> Optional[Tuple[datetime, str]]:
    """The newest second-factor proof this session holds: (when, method) or None."""
    found = []
    if session.stepup_at is not None:
        found.append((session.stepup_at, session.stepup_method or "mfa"))
    if "mfa" in (session.amr or []):
        found.append((session.auth_time, "login_mfa"))
    return max(found, key=lambda x: x[0]) if found else None


def is_fresh(session, now: Optional[datetime] = None) -> bool:
    p = proof(session)
    now = now or datetime.now(timezone.utc)
    return p is not None and now - p[0] <= timedelta(minutes=settings.ADMIN_STEPUP_MINUTES)


def require_stepup(request: Request, ctx=Depends(get_session_and_user), actor: User = Depends(require_admin)) -> User:
    """Dependency for sensitive admin routes. Runs after `require_admin`, so a caller without admin rights gets that refusal."""
    session, user, _ = ctx
    if not settings.ADMIN_MFA_REQUIRED or getattr(session, "api_token", None) is not None:
        return actor
    p = proof(session)
    if p is None or not is_fresh(session):
        raise HTTPException(status_code=403, detail=STEPUP_REQUIRED, headers={"X-Step-Up": "required"})
    request.state.stepup_method = p[1]  # stamped onto the audit event of the action (audit.service.record)
    return actor


class StepUpBody(BaseModel):
    code: str = Field(..., min_length=1, max_length=64)


@router.get("/me/step-up")
def step_up_status(ctx=Depends(get_session_and_user)):
    """Is this session's proof fresh? Lets the UI skip a prompt it does not need."""
    session, user, _ = ctx
    p = proof(session)
    required = bool(settings.ADMIN_MFA_REQUIRED and user.is_admin and getattr(session, "api_token", None) is None)
    expires = (p[0] + timedelta(minutes=settings.ADMIN_STEPUP_MINUTES)).isoformat() if p and is_fresh(session) else None
    return {"required": required, "fresh": (not required) or is_fresh(session), "window_minutes": settings.ADMIN_STEPUP_MINUTES, "expires_at": expires}


@router.post("/me/step-up")
def step_up(body: StepUpBody, request: Request, ctx=Depends(get_session_and_user), db: Session = Depends(get_db)):
    """Prove a second factor again with an authenticator or recovery code. Wrong codes count against the account-security limits."""
    session, user, _ = ctx
    if getattr(session, "api_token", None) is not None or not user.is_admin:
        raise HTTPException(status_code=403, detail="Forbidden")
    if not (user.mfa and user.mfa.enabled):
        # A passkey-only administrator proves themselves by signing in again with the passkey (that counts as the proof).
        raise HTTPException(status_code=400, detail="Sign out and sign in again with your passkey to confirm this action")
    try:
        mfa_guard(request, user)
    except HTTPException as e:
        if e.status_code == 429:
            record(db, AuditAction.ADMIN_STEPUP_THROTTLED, request, user, user.id, "user")
            db.commit()
            logger.warning("stepup.throttled", user_id=user.id)
        raise
    method = mfa_service.verify_second_factor(db, user, body.code)
    if method is None:
        mfa_failed(request, user)
        record(db, AuditAction.ADMIN_STEPUP_FAILED, request, user, user.id, "user")
        db.commit()
        logger.warning("stepup.failed", user_id=user.id)
        raise HTTPException(status_code=403, detail="Invalid or expired code")
    session.stepup_at = datetime.now(timezone.utc)
    session.stepup_method = method
    record(db, AuditAction.ADMIN_STEPUP, request, user, user.id, "user", {"method": method})
    db.commit()
    return {"success": True, "method": method, "window_minutes": settings.ADMIN_STEPUP_MINUTES}
