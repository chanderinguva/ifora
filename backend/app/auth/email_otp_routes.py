"""Email OTP second factor (IFORA-60): self-service enrolment and the login-time send. Verification at login is `/login/mfa`
with `factor: "email"`, so there is one place that burns the challenge, counts failures and starts the session."""

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app import mailer, ratelimit
from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.auth import email_otp, mfa_service, notify
from backend.app.auth.deps import check_origin, get_session_and_user
from backend.app.auth.mfa_model import UserEmailOTP
from backend.app.auth.mfa_routes import CodeOnly, PasswordOnly, _reauth, mfa_failed, mfa_guard
from backend.app.auth.sessions_util import revoke_user_sessions
from backend.app.db import get_db
from backend.app.users.model import User

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["mfa"])


class SendBody(BaseModel):
    mfa_token: str = Field(..., max_length=128)


def _throttle_send(request: Request, user: User) -> None:
    """At most 3 code requests a minute per account and per address; refused (429) before anything is generated or sent."""
    ip = ratelimit.client_ip(request)
    ratelimit.check("email_otp_send_user", str(user.id), email_otp.SEND_LIMIT)
    ratelimit.check("email_otp_send_ip", ip, email_otp.SEND_LIMIT)
    ratelimit.hit("email_otp_send_user", str(user.id), email_otp.SEND_WINDOW_SECONDS)
    ratelimit.hit("email_otp_send_ip", ip, email_otp.SEND_WINDOW_SECONDS)


def _deliver(user: User, code: str, why: str) -> None:
    try:
        email_otp.send(user, code, why)
    except Exception as e:  # noqa: BLE001 - the address and code never go to the log
        logger.warning("email_otp.send_failed", error=type(e).__name__)
        raise HTTPException(status_code=502, detail="The mail server did not accept the message")


@router.get("/me/mfa/email")
def email_status(ctx=Depends(get_session_and_user), db: Session = Depends(get_db)):
    user = ctx[1]
    return {"allowed": email_otp.allowed(db, user), "mail_configured": mailer.configured(), "enabled": email_otp.is_enabled(user),
            "pending": bool(user.email_otp and not user.email_otp.enabled), "required": email_otp.audience_policy(db, user) == "required" and user.is_admin,
            "address": user.email}


@router.post("/me/mfa/email/setup")
def email_setup(body: PasswordOnly, request: Request, ctx=Depends(get_session_and_user), db: Session = Depends(get_db)):
    """Start enrolment: re-check the password, then mail a code to the account's own address."""
    user = ctx[1]
    _reauth(user, body.password, request)
    if not email_otp.allowed(db, user):
        raise HTTPException(status_code=403, detail="Email codes are not turned on for your account")
    if not mailer.configured():
        raise HTTPException(status_code=503, detail="Email is not set up on this server")
    if email_otp.is_enabled(user):
        raise HTTPException(status_code=409, detail="Email codes are already turned on")
    row = user.email_otp
    if row is None:
        row = UserEmailOTP(user_id=user.id, enabled=False)
        db.add(row)
        db.flush()
    if email_otp.locked(row):
        raise HTTPException(status_code=429, detail="Too many wrong codes. Try again later.")
    _throttle_send(request, user)
    code = email_otp.issue(db, row)
    db.commit()
    _deliver(user, code, "turns on email codes for your account")
    return {"sent": True, "expires_in": email_otp.CODE_TTL_SECONDS}


@router.post("/me/mfa/email/enable")
def email_enable(body: CodeOnly, request: Request, ctx=Depends(get_session_and_user), db: Session = Depends(get_db)):
    session, user, _ = ctx
    mfa_guard(request, user)
    row = user.email_otp
    if row is None or row.enabled:
        raise HTTPException(status_code=409, detail="No pending email code setup")
    result = email_otp.verify(db, user, body.code, enrolling=True)
    if result is not True:
        if result is None:
            record(db, AuditAction.EMAIL_OTP_LOCKED, request, user, user.id, "user", {"during": "enrolment"})
        db.commit()  # keep the attempt count / lockout
        mfa_failed(request, user)
        raise HTTPException(status_code=400, detail="Invalid code")
    row.enabled, row.enabled_at = True, datetime.now(timezone.utc)
    revoked = revoke_user_sessions(db, user.id, except_id=session.id)
    record(db, AuditAction.EMAIL_OTP_ENABLED, request, user, user.id, "user", {"other_sessions_revoked": revoked})
    db.commit()
    notify.notify(db, user, "Email verification codes turned on", request.client.host if request.client else "")
    return {"enabled": True}


@router.post("/me/mfa/email/disable")
def email_disable(body: PasswordOnly, request: Request, ctx=Depends(get_session_and_user), db: Session = Depends(get_db)):
    session, user, _ = ctx
    _reauth(user, body.password, request)
    if not email_otp.is_enabled(user):
        raise HTTPException(status_code=409, detail="Email codes are not turned on")
    if email_otp.audience_policy(db, user) == "required" and user.is_admin:
        raise HTTPException(status_code=409, detail="Your organisation requires email codes for administrators")
    email_otp.remove(db, user)
    revoked = revoke_user_sessions(db, user.id, except_id=session.id)
    record(db, AuditAction.EMAIL_OTP_DISABLED, request, user, user.id, "user", {"other_sessions_revoked": revoked})
    db.commit()
    notify.notify(db, user, "Email verification codes turned off", request.client.host if request.client else "")
    return {"enabled": False}


@router.post("/login/mfa/email/send")
def login_email_send(body: SendBody, request: Request, db: Session = Depends(get_db)):
    """Mail a sign-in code to someone who has passed the password step (holds a live challenge token)."""
    check_origin(request)
    ip = ratelimit.client_ip(request)
    ratelimit.check("login", ip, 10)
    ch = mfa_service.load_challenge(db, body.mfa_token)
    user = db.get(User, ch.user_id) if ch is not None else None
    if ch is None or user is None or user.status != "active" or user.is_locked_out() or not email_otp.usable_at_login(db, user):
        ratelimit.hit("login", ip, 300)
        raise HTTPException(status_code=401, detail="Invalid or expired sign-in")
    if not mailer.configured():
        raise HTTPException(status_code=503, detail="Email is not set up on this server")
    row = user.email_otp
    if email_otp.locked(row):
        raise HTTPException(status_code=429, detail="Too many wrong codes. Try again later.")
    _throttle_send(request, user)
    code = email_otp.issue(db, row)
    db.commit()
    _deliver(user, code, "lets you finish signing in")
    return {"sent": True, "expires_in": email_otp.CODE_TTL_SECONDS}
