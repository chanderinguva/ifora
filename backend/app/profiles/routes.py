"""End-user self-service: profile, password change, dashboard data."""

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.auth.deps import get_session_and_user
from backend.app.auth.session import Session as AuthSession
from backend.app.auth.session import SessionStatus
from backend.app.auth.sessions_util import revoke_user_sessions
from backend.app.db import get_db
from backend.app.profiles import catalog as cat
from backend.app.profiles.schemas import PasswordChange, validate_attributes
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


def _profile(user: User, db: Session) -> dict:
    d = user.to_dict()
    d["groups"] = [{"id": g.id, "name": g.name} for g in user.groups]
    schema = cat.catalog(db)
    d["attribute_schema"] = [a.to_dict() for a in schema]
    d["editable_attributes"] = [a.key for a in schema if a.user_editable]
    return d


@router.get("/profile")
def get_profile(ctx=Depends(get_session_and_user), db: Session = Depends(get_db)):
    return _profile(ctx[1], db)


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
        try:
            cleaned = cat.validate_values(db, body.profile_attributes, only_editable_by_user=True, current=current)
        except cat.PermissionError_ as e:
            raise HTTPException(status_code=e.status, detail=e.message)
        except cat.AttributeError_ as e:
            raise HTTPException(status_code=422, detail=str(e))
        # Only the keys sent change (null/empty clears one); everything else, admin-managed values included, is untouched.
        merged = dict(current)
        for k, v in cleaned.items():
            if v is None:
                merged.pop(k, None)
            else:
                merged[k] = v
        user.set_profile_attributes(merged)
        changed["profile_attributes"] = sorted(body.profile_attributes)
    if changed:
        record(db, AuditAction.PROFILE_UPDATED, request, user, user.id, "user", {"changed": changed})
    db.commit()
    db.refresh(user)
    return _profile(user, db)


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
    from backend.app.security_policy import service as policy

    policy.set_checked(db, user, body.new_password)
    revoked = revoke_user_sessions(db, user.id, except_id=session.id)
    record(db, AuditAction.USER_PASSWORD_CHANGED, request, user, user.id, "user", {"by": "self", "sessions_revoked": revoked})
    db.commit()
    from backend.app.auth import notify

    notify.notify(db, user, "Password changed", request.client.host if request.client else "")
    return {"success": True, "other_sessions_revoked": revoked}


# Own recent security-relevant events (Okta "recent activity", Entra "My sign-ins"). Only the user's own
# rows, only these actions, and only fields that are safe to show them.
_ACTIVITY = (
    "LOGIN_SUCCESS", "LOGIN_FAILURE", "LOGOUT", "USER_PASSWORD_CHANGED", "MFA_ENABLED", "MFA_DISABLED",
    "MFA_RESET", "MFA_RECOVERY_USED", "MFA_CHALLENGE_FAILED", "MFA_RECOVERY_REGENERATED", "PASSKEY_REGISTERED", "PASSKEY_REMOVED",
    "PASSKEY_LOGIN_FAILED", "PASSKEY_POLICY_CHANGED", "SESSION_REVOKED", "SESSIONS_REVOKED", "ROLE_SWITCHED",
)
_FAILURES = {"LOGIN_FAILURE", "MFA_CHALLENGE_FAILED", "PASSKEY_LOGIN_FAILED"}


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@router.get("/activity")
def my_activity(response: Response, limit: int = 20, ctx=Depends(get_session_and_user), db: Session = Depends(get_db)):
    from backend.app.audit.model import AuditEvent
    from backend.app.auth import device

    _no_store(response)
    _, user, _ = ctx
    rows = (
        db.query(AuditEvent)
        .filter(AuditEvent.actor_id == str(user.id), AuditEvent.action.in_(_ACTIVITY))
        .order_by(AuditEvent.timestamp.desc(), AuditEvent.id.desc())
        .limit(max(1, min(limit, 50)))
        .all()
    )
    return {
        "items": [
            {
                "timestamp": r.timestamp.isoformat(),
                "action": r.action,
                "result": "failure" if r.action in _FAILURES else "success",
                "ip_address": r.actor_ip_address,
                "device": device.label((r.event_metadata or {}).get("user_agent")) if (r.event_metadata or {}).get("user_agent") else None,
                "method": (r.event_metadata or {}).get("method"),
            }
            for r in rows
        ]
    }


# ---- my sessions and devices -----------------------------------------------------------------------------------------


class ReauthBody(BaseModel):
    password: str = Field(..., max_length=128)


def _own_active_sessions(db: Session, user: User):
    return [s for s in db.query(AuthSession).filter(AuthSession.user_id == user.id, AuthSession.status == SessionStatus.ACTIVE.value)
            .order_by(AuthSession.created_at.desc()).all() if not s.is_expired]


@router.get("/sessions")
def my_sessions(response: Response, ctx=Depends(get_session_and_user), db: Session = Depends(get_db)):
    """The caller's own live sessions. Each carries an opaque handle, never the database id; the current one is marked."""
    from backend.app.auth import device

    _no_store(response)
    session, user, _ = ctx
    return {
        "items": [
            {"handle": device.handle(user.id, s.id), "current": s.id == session.id, "device": device.label(s.user_agent),
             "ip_address": s.ip_address, "created_at": s.created_at.isoformat(), "last_activity_at": s.last_activity_at.isoformat() if s.last_activity_at else None,
             "expires_at": s.expires_at.isoformat()}
            for s in _own_active_sessions(db, user)
        ]
    }


@router.post("/sessions/revoke-others")
def revoke_other_sessions(body: ReauthBody, request: Request, response: Response, ctx=Depends(get_session_and_user), db: Session = Depends(get_db)):
    """Sign this account out everywhere except here. Needs the password again (throttled like the other account-security actions)."""
    from backend.app.auth.mfa_routes import _reauth

    _no_store(response)
    session, user, _ = ctx
    _reauth(user, body.password, request)
    revoked = revoke_user_sessions(db, user.id, except_id=session.id)
    record(db, AuditAction.SESSIONS_REVOKED, request, user, user.id, "user", {"count": revoked})
    db.commit()
    return {"revoked": revoked}


@router.post("/sessions/{handle}/revoke")
def revoke_session(handle: str, body: ReauthBody, request: Request, response: Response, ctx=Depends(get_session_and_user), db: Session = Depends(get_db)):
    """Sign out one other session. A handle that is not this caller's live session is a 404, whoever it belongs to."""
    from backend.app.auth import device
    from backend.app.auth.mfa_routes import _reauth

    _no_store(response)
    session, user, _ = ctx
    _reauth(user, body.password, request)
    target = next((s for s in _own_active_sessions(db, user) if device.matches(handle, user.id, s.id)), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if target.id == session.id:
        raise HTTPException(status_code=400, detail="This is the session you are using; sign out instead")
    target.status = SessionStatus.REVOKED.value
    record(db, AuditAction.SESSION_REVOKED, request, user, user.id, "user", {"device": device.label(target.user_agent), "ip": target.ip_address})
    db.commit()
    return {"revoked": 1}
