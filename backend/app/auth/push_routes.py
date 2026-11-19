"""Push sign-in approval (IFORA-77): enrolling browsers, the login-screen request, and the device's own answer endpoints."""

from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app import ratelimit
from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.auth import mfa_service, notify, push_mfa
from backend.app.auth.deps import check_origin, get_session_and_user
from backend.app.auth.mfa_model import MFAChallenge, PushChallenge, PushDevice
from backend.app.auth.mfa_routes import PasswordOnly, _reauth, mfa_guard
from backend.app.auth.sessions_util import revoke_user_sessions
from backend.app.config import settings
from backend.app.db import get_db
from backend.app.users.model import User

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["mfa"])


class TokenBody(BaseModel):
    mfa_token: str = Field(..., max_length=128)


class EnrolBody(BaseModel):
    password: str = Field(..., max_length=256)
    name: str = Field("Browser", max_length=80)
    endpoint: str = Field(..., max_length=2048)


class Respond(BaseModel):
    challenge_id: int
    number: Optional[str] = Field(None, pattern="^[0-9]{2}$")  # none = "this wasn't me"


def _device_view(d) -> dict:
    return {"id": d.id, "name": d.name, "created_at": d.created_at.isoformat() if d.created_at else None,
            "last_used_at": d.last_used_at.isoformat() if d.last_used_at else None}


# ---- enrolment (signed in) -------------------------------------------------------------------------------------

@router.get("/me/mfa/push")
def push_status(ctx=Depends(get_session_and_user), db: Session = Depends(get_db)):
    user = ctx[1]
    return {"allowed": push_mfa.allowed(db, user), "configured": push_mfa.configured(), "required": push_mfa.required_for(db, user),
            "public_key": push_mfa.public_key() if push_mfa.configured() else None, "max_devices": push_mfa.MAX_DEVICES,
            "devices": [_device_view(d) for d in sorted(user.push_devices, key=lambda x: x.id)]}


@router.post("/me/mfa/push/devices", status_code=201)
def push_add_device(body: EnrolBody, request: Request, ctx=Depends(get_session_and_user), db: Session = Depends(get_db)):
    """Register this browser: re-check the password, make sure the push service accepts a wake-up for it, and hand back its secret once."""
    session, user, _ = ctx
    mfa_guard(request, user)
    _reauth(user, body.password, request)
    if not push_mfa.allowed(db, user):
        raise HTTPException(status_code=403, detail="Push approval is not turned on for your account")
    if not push_mfa.configured():
        raise HTTPException(status_code=503, detail="Push notifications are not set up on this server")
    if not push_mfa.valid_endpoint(body.endpoint):
        raise HTTPException(status_code=422, detail="That is not a supported browser push address")
    if len(user.push_devices) >= push_mfa.MAX_DEVICES:
        raise HTTPException(status_code=409, detail=f"At most {push_mfa.MAX_DEVICES} devices; remove one first")
    if db.query(PushDevice).filter(PushDevice.endpoint_hash == push_mfa._h(body.endpoint)).first() is not None:
        raise HTTPException(status_code=409, detail="This browser is already registered")
    if push_mfa.send(body.endpoint) != "ok":
        raise HTTPException(status_code=400, detail="The push service did not accept this browser")
    device, secret = push_mfa.enrol(db, user, body.name, body.endpoint)
    revoked = revoke_user_sessions(db, user.id, except_id=session.id)
    record(db, AuditAction.PUSH_DEVICE_ADDED, request, user, user.id, "user", {"device_id": device.id, "other_sessions_revoked": revoked})
    db.commit()
    notify.notify(db, user, "A device was added for push sign-in approval", request.client.host if request.client else "")
    return {"id": device.id, "name": device.name, "secret": secret}


@router.post("/me/mfa/push/devices/{device_id}/remove")
def push_remove_device(device_id: int, body: PasswordOnly, request: Request, ctx=Depends(get_session_and_user), db: Session = Depends(get_db)):
    session, user, _ = ctx
    _reauth(user, body.password, request)
    device = next((d for d in user.push_devices if d.id == device_id), None)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    if push_mfa.required_for(db, user) and len(user.push_devices) == 1:
        raise HTTPException(status_code=409, detail="Your organisation requires a push device for administrators")
    db.delete(device)
    revoked = revoke_user_sessions(db, user.id, except_id=session.id)
    record(db, AuditAction.PUSH_DEVICE_REMOVED, request, user, user.id, "user", {"device_id": device_id, "other_sessions_revoked": revoked})
    db.commit()
    notify.notify(db, user, "A device was removed from push sign-in approval", request.client.host if request.client else "")
    return {"removed": True}


# ---- login screen ----------------------------------------------------------------------------------------------

def _login_context(request: Request, body: TokenBody, db: Session):
    check_origin(request)
    ip = ratelimit.client_ip(request)
    ratelimit.check("login", ip, 10)
    ch = mfa_service.load_challenge(db, body.mfa_token)
    user = db.get(User, ch.user_id) if ch is not None else None
    if ch is None or user is None or user.status != "active" or user.is_locked_out() or not push_mfa.usable_at_login(db, user):
        ratelimit.hit("login", ip, 300)
        raise HTTPException(status_code=401, detail="Invalid or expired sign-in")
    return ch, user, ip


@router.post("/login/mfa/push/start")
def login_push_start(body: TokenBody, request: Request, db: Session = Depends(get_db)):
    """Show-the-number step: create the request and wake the person's devices. The number is returned only to this login screen."""
    ch, user, ip = _login_context(request, body, db)
    if push_mfa.locked(user):
        raise HTTPException(status_code=429, detail="Too many wrong approvals. Try again later.")
    ratelimit.check("push_start_user", str(user.id), push_mfa.START_LIMIT)
    ratelimit.check("push_start_ip", ip, push_mfa.START_LIMIT)
    ratelimit.hit("push_start_user", str(user.id), push_mfa.START_WINDOW_SECONDS)
    ratelimit.hit("push_start_ip", ip, push_mfa.START_WINDOW_SECONDS)
    row = push_mfa.start(db, user, ch, ip)
    if push_mfa.notify_devices(db, user) == 0:
        db.delete(row)
        db.commit()
        raise HTTPException(status_code=502, detail="Could not reach your devices")
    db.commit()
    return {"number": row.number, "expires_in": push_mfa.CHALLENGE_TTL_SECONDS}


@router.post("/login/mfa/push/status")
def login_push_status(body: TokenBody, request: Request, db: Session = Depends(get_db)):
    """Poll for the answer. Does not consume anything and never counts as a failed attempt."""
    check_origin(request)
    ratelimit.check("login", ratelimit.client_ip(request), 10)
    ch = db.query(MFAChallenge).filter(MFAChallenge.token_hash == mfa_service._h(body.mfa_token)).first() if body.mfa_token else None
    if ch is None or ch.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Invalid or expired sign-in")
    row = push_mfa.for_login(db, ch)
    return {"state": push_mfa.state_of(row)}


# ---- the enrolled browser answers ------------------------------------------------------------------------------

def _device_user(request: Request, db: Session):
    check_origin(request)
    ip = ratelimit.client_ip(request)
    ratelimit.check("push_device", ip, 30)
    device = push_mfa.device_for(db, request.headers.get("authorization"))
    user = device.user if device is not None else None
    if device is None or user is None or user.status != "active" or user.is_locked_out():
        ratelimit.hit("push_device", ip, 300)
        raise HTTPException(status_code=401, detail="Unknown device")
    device.last_used_at = datetime.now(timezone.utc)
    return device, user


@router.get("/device/push/pending")
def device_pending(request: Request, db: Session = Depends(get_db)):
    _, user = _device_user(request, db)
    row = push_mfa.pending_for(db, user)
    db.commit()
    return {"pending": False} if row is None else {"pending": True, **push_mfa.view(row)}


@router.post("/device/push/respond")
def device_respond(body: Respond, request: Request, db: Session = Depends(get_db)):
    _, user = _device_user(request, db)
    row = db.query(PushChallenge).filter(PushChallenge.id == body.challenge_id, PushChallenge.user_id == user.id).with_for_update().first()
    if row is None or push_mfa.state_of(row) != "pending":
        raise HTTPException(status_code=404, detail="No pending request")
    if body.number is not None and body.number not in row.choices:
        raise HTTPException(status_code=422, detail="Not one of the offered numbers")
    ch = db.get(MFAChallenge, row.mfa_challenge_id)
    if body.number is not None and body.number == row.number:
        row.status = "approved"
        record(db, AuditAction.PUSH_APPROVED, request, user, user.id, "user")
        db.commit()
        return {"result": "approved"}
    row.status = "denied"
    wrong = body.number is not None
    if ch is not None:
        # "This wasn't me" ends the sign-in; a wrong pick counts like a wrong code (challenge, account lockout, push lockout).
        ch.attempts = settings.MFA_CHALLENGE_MAX_ATTEMPTS if not wrong else ch.attempts + 1
    if wrong:
        from backend.app.security_policy import service as sec_policy

        user.failed_login_attempts += 1
        pol = sec_policy.get(db)
        if user.failed_login_attempts >= pol.max_failed_attempts:
            user.lockout_until = datetime.now(timezone.utc) + timedelta(minutes=pol.lockout_minutes)
            user.failed_login_attempts = 0
    # A decline is as strong a signal as a wrong pick: someone who knows the password is prompting this person. Both count toward
    # blocking new requests, so a stolen password cannot be used to keep pinging their devices.
    ratelimit.hit("push_fail_user", str(user.id), push_mfa.FAIL_WINDOW_SECONDS)
    if push_mfa.locked(user):
        record(db, AuditAction.PUSH_LOCKED, request, user, user.id, "user")
    record(db, AuditAction.PUSH_DENIED, request, user, user.id, "user", {"reason": "wrong_number" if wrong else "declined"})
    db.commit()
    return {"result": "denied"}
