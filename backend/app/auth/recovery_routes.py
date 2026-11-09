"""Forgot password, accept invitation, and the forced password change (Okta PASSWORD_EXPIRED).

- Unauthenticated endpoints never reveal whether an email exists (same response either way, rate-limited per IP and
  per address). Reset/invite tokens are single use, short lived, hashed at rest and travel in the URL fragment.
- Setting a password this way ends every session of the user and moves provisioned/recovery/password_expired/locked_out
  accounts to active. Suspended, deprovisioned and staged accounts cannot use it.
- An expired password can only be replaced by proving the old one (verified with the same lockout accounting as login).
"""

from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from passlib.hash import argon2
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy.orm import Session


from backend.app import mailer, ratelimit
from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.auth import password_tokens
from backend.app.auth.deps import check_origin
from backend.app.auth.routes import _DUMMY_HASH
from backend.app.auth.sessions_util import revoke_user_sessions
from backend.app.config import settings
from backend.app.db import get_db
from backend.app.profiles.schemas import validate_password
from backend.app.users.model import User

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["account-recovery"])

RESETTABLE = ("active", "provisioned", "recovery", "password_expired", "locked_out")
_GENERIC = {"success": True, "message": "If an account exists for that address, an email with instructions is on its way."}


class ForgotBody(BaseModel):
    email: EmailStr


class SetPasswordBody(BaseModel):
    token: str = Field(..., min_length=10, max_length=100)
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _pw(cls, v):
        return validate_password(v)


class ExpiredBody(BaseModel):
    email: EmailStr
    current_password: str = Field(..., max_length=128)
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _pw(cls, v):
        return validate_password(v)


def send_link(user: User, purpose: str, raw: str, db: Session) -> bool:
    """Email the link, using the organization's template. Returns False (without raising) when mail is unavailable or fails."""
    from backend.app.branding import templates

    url = password_tokens.link(raw, purpose)
    valid = f"{settings.INVITE_HOURS} hours" if purpose == "invite" else f"{settings.PASSWORD_RESET_MINUTES} minutes"
    subject, body = templates.compose(db, "invite" if purpose == "invite" else "reset", first_name=user.first_name, link=url, valid_for=valid)
    try:
        mailer.send(mailer.build(user.email, subject, body), timeout=10)
        return True
    except Exception as e:  # noqa: BLE001 - never leak delivery details to an anonymous caller
        logger.warning("mail.send_failed", purpose=purpose, user_id=user.id, error=type(e).__name__)
        return False


@router.post("/auth/forgot-password")
def forgot_password(body: ForgotBody, request: Request, db: Session = Depends(get_db)):
    check_origin(request)
    ip = ratelimit.client_ip(request)
    email = body.email.lower()
    ratelimit.check("pwreset_ip", ip, 10)
    ratelimit.check("pwreset_email", email, 3)
    ratelimit.hit("pwreset_ip", ip, 3600)
    ratelimit.hit("pwreset_email", email, 3600)
    user = db.query(User).filter(User.email == email).first()
    if user is not None and user.status in RESETTABLE and mailer.configured():
        raw = password_tokens.issue(db, user, "reset")
        record(db, AuditAction.PASSWORD_RESET_REQUESTED, request, None, user.id, "user", {})
        db.commit()
        send_link(user, "reset", raw, db)
    return _GENERIC


@router.post("/auth/reset-password")
def reset_password(body: SetPasswordBody, request: Request, db: Session = Depends(get_db)):
    """Complete a reset or an invitation with the emailed token."""
    check_origin(request)
    ip = ratelimit.client_ip(request)
    ratelimit.check("pwtoken_ip", ip, 20)
    token = password_tokens.lookup(db, body.token)
    user = db.get(User, token.user_id) if token else None
    if token is None or user is None or user.status not in RESETTABLE:
        ratelimit.hit("pwtoken_ip", ip, 3600)
        raise HTTPException(status_code=400, detail="This link is invalid or has expired")
    from backend.app.security_policy import service as policy

    policy.validate_new(db, body.new_password, user)  # before the claim, so a weak password does not burn the link
    now = datetime.now(timezone.utc)
    # claim atomically: of two concurrent requests with the same token only one may win
    claimed = (
        db.query(password_tokens.PasswordToken)
        .filter(password_tokens.PasswordToken.id == token.id, password_tokens.PasswordToken.used_at.is_(None))
        .update({"used_at": now}, synchronize_session=False)
    )
    if claimed != 1:
        db.rollback()
        ratelimit.hit("pwtoken_ip", ip, 3600)
        raise HTTPException(status_code=400, detail="This link is invalid or has expired")
    policy.apply_new(db, user, body.new_password)
    user.failed_login_attempts = 0
    user.lockout_until = None
    if user.status != "active":
        user.status = "active"
    revoked = revoke_user_sessions(db, user.id)
    record(db, AuditAction.PASSWORD_RESET_COMPLETED, request, None, user.id, "user",
           {"via": token.purpose, "sessions_revoked": revoked})
    db.commit()
    return {"success": True, "message": "Password set. You can sign in now."}


@router.post("/auth/change-expired-password")
def change_expired_password(body: ExpiredBody, request: Request, db: Session = Depends(get_db)):
    """For accounts in `password_expired`: prove the current password, choose a new one, then sign in normally."""
    check_origin(request)
    ip = ratelimit.client_ip(request)
    ratelimit.check("login", ip, settings.RATE_LIMIT_LOGIN_FAILURES)
    invalid = HTTPException(status_code=401, detail="Invalid credentials")
    user = db.query(User).filter(User.email == body.email.lower()).first()
    if user is None or user.is_locked_out() or user.status != "password_expired":
        try:
            argon2.verify(body.current_password, _DUMMY_HASH)
        except Exception:
            pass
        ratelimit.hit("login", ip, settings.RATE_LIMIT_LOGIN_WINDOW_SECONDS)
        raise invalid
    from backend.app.security_policy import service as policy

    pol = policy.get(db)
    if not user.verify_password(body.current_password):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= pol.max_failed_attempts:
            user.lockout_until = datetime.now(timezone.utc) + timedelta(minutes=pol.lockout_minutes)
            user.failed_login_attempts = 0
        db.commit()
        ratelimit.hit("login", ip, settings.RATE_LIMIT_LOGIN_WINDOW_SECONDS)
        raise invalid
    if body.new_password == body.current_password:
        raise HTTPException(status_code=422, detail="Choose a password different from the current one")
    policy.set_checked(db, user, body.new_password)
    user.status = "active"
    user.failed_login_attempts = 0
    revoke_user_sessions(db, user.id)
    record(db, AuditAction.PASSWORD_RESET_COMPLETED, request, None, user.id, "user", {"via": "expired_password"})
    db.commit()
    return {"success": True, "message": "Password changed. You can sign in now."}
