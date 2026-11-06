"""End-user self-service: profile, password change, dashboard data."""

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.auth.deps import get_session_and_user
from backend.app.auth.session import Session as AuthSession
from backend.app.auth.session import SessionStatus
from backend.app.auth.sessions_util import revoke_user_sessions
from backend.app.db import get_db
from backend.app.profiles.schemas import SELF_EDITABLE, PasswordChange, validate_attributes
from backend.app.users.model import User

router = APIRouter(prefix="/me", tags=["profile"])


class ProfileUpdate(BaseModel):
    first_name: str | None = Field(None, min_length=1, max_length=100)
    last_name: str | None = Field(None, min_length=1, max_length=100)
    profile_attributes: Dict[str, Any] | None = None

    @field_validator("profile_attributes")
    @classmethod
    def _attrs(cls, v):
        return None if v is None else validate_attributes(v)


def _profile(user: User) -> dict:
    d = user.to_dict()
    d["groups"] = [{"id": g.id, "name": g.name} for g in user.groups]
    d["editable_attributes"] = sorted(SELF_EDITABLE)
    return d


@router.get("/profile")
def get_profile(ctx=Depends(get_session_and_user)):
    return _profile(ctx[1])


@router.patch("/profile")
def update_profile(
    body: ProfileUpdate,
    request: Request,
    ctx=Depends(get_session_and_user),
    db: Session = Depends(get_db),
):
    _, user, _ = ctx
    changed: Dict[str, Any] = {}
    if body.first_name is not None:
        user.first_name = body.first_name
        changed["first_name"] = True
    if body.last_name is not None:
        user.last_name = body.last_name
        changed["last_name"] = True
    if body.profile_attributes is not None:
        current = user.get_profile_attributes()
        # Admin-managed keys stay as they are; users only control SELF_EDITABLE keys.
        merged = {k: v for k, v in current.items() if k not in SELF_EDITABLE}
        for k, v in body.profile_attributes.items():
            if k not in SELF_EDITABLE:
                raise HTTPException(status_code=403, detail=f"Attribute '{k}' cannot be edited by users")
            if v is not None:
                merged[k] = v
        user.set_profile_attributes(merged)
        changed["profile_attributes"] = sorted(body.profile_attributes)
    if changed:
        record(db, AuditAction.PROFILE_UPDATED, request, user, user.id, "user", {"changed": changed})
    db.commit()
    db.refresh(user)
    return _profile(user)


@router.post("/password")
def change_password(
    body: PasswordChange,
    request: Request,
    ctx=Depends(get_session_and_user),
    db: Session = Depends(get_db),
):
    session, user, _ = ctx
    if not user.verify_password(body.current_password):
        raise HTTPException(status_code=403, detail="Current password is incorrect")
    user.set_password(body.new_password)
    revoked = revoke_user_sessions(db, user.id, except_id=session.id)
    record(db, AuditAction.USER_PASSWORD_CHANGED, request, user, user.id, "user", {"by": "self", "sessions_revoked": revoked})
    db.commit()
    return {"success": True, "other_sessions_revoked": revoked}


@router.get("/sessions")
def my_sessions(ctx=Depends(get_session_and_user), db: Session = Depends(get_db)):
    session, user, _ = ctx
    rows = (
        db.query(AuthSession)
        .filter(AuthSession.user_id == user.id, AuthSession.status == SessionStatus.ACTIVE.value)
        .order_by(AuthSession.created_at.desc())
        .all()
    )
    return {
        "items": [
            {**s.to_dict(), "current": s.id == session.id, "ip_address": s.ip_address, "user_agent": s.user_agent}
            for s in rows
            if not s.is_expired
        ]
    }
