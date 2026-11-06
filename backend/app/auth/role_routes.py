"""Per-session role view: an admin can work as a normal user and step back up with their password.

This is least privilege, not impersonation: the same person, same account, but this session's admin
powers are switched off server-side (`require_admin`), so a hijacked or careless user-view session cannot
administer anything. Other sessions of the same account are not affected.
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app import ratelimit
from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.auth.deps import get_session_and_user
from backend.app.config import settings
from backend.app.db import get_db

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["role"])


class StepUp(BaseModel):
    password: str = Field(..., max_length=128)


def _view(user, session) -> dict:
    return {"user": {**user.to_dict(), "acting_as_user": session.acting_as_user}}


@router.post("/me/role/user")
def switch_to_user_view(request: Request, ctx=Depends(get_session_and_user), db: Session = Depends(get_db)):
    """Drop admin powers for this session. No re-authentication needed: it only reduces privilege."""
    session, user, _ = ctx
    if not user.is_admin:
        raise HTTPException(status_code=400, detail="Only administrators have a role to switch")
    if not session.acting_as_user:
        session.acting_as_user = True
        record(db, AuditAction.ROLE_SWITCHED, request, user, user.id, "user", {"to": "user"})
        db.commit()
    return _view(user, session)


@router.post("/me/role/admin")
def switch_to_admin_view(
    body: StepUp, request: Request, ctx=Depends(get_session_and_user), db: Session = Depends(get_db)
):
    """Regain admin powers for this session. Needs the current password (step-up), since it raises privilege."""
    session, user, _ = ctx
    if not user.is_admin:
        raise HTTPException(status_code=400, detail="Only administrators have a role to switch")
    ip = ratelimit.client_ip(request)
    ratelimit.check("login", ip, settings.RATE_LIMIT_LOGIN_FAILURES)
    if not user.verify_password(body.password):
        ratelimit.hit("login", ip, settings.RATE_LIMIT_LOGIN_WINDOW_SECONDS)
        raise HTTPException(status_code=403, detail="Password is incorrect")
    if session.acting_as_user:
        session.acting_as_user = False
        record(db, AuditAction.ROLE_SWITCHED, request, user, user.id, "user", {"to": "admin"})
        db.commit()
    return _view(user, session)
