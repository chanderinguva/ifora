"""MFA: login second step, self-service enrolment, and admin reset."""

from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app import ratelimit
from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.auth import mfa, mfa_service
from backend.app.auth.deps import check_origin, get_session_and_user, require_admin
from backend.app.auth.mfa_model import UserMFA
from backend.app.auth.routes import complete_login
from backend.app.auth.sessions_util import revoke_user_sessions
from backend.app.config import settings
from backend.app.db import get_db
from backend.app.users.model import User
from backend.app.users.routes import _get_or_404, _guard_target

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["mfa"])


class MfaLogin(BaseModel):
    mfa_token: str = Field(..., max_length=128)
    code: str = Field(..., max_length=64)


class PasswordOnly(BaseModel):
    password: str = Field(..., max_length=128)


class EnrolStart(BaseModel):
    password: str = Field(..., max_length=128)
    enrollment_code: Optional[str] = Field(default=None, max_length=64)


class CodeOnly(BaseModel):
    code: str = Field(..., max_length=64)


class PasswordAndCode(BaseModel):
    password: str = Field(..., max_length=128)
    code: str = Field(..., max_length=64)


def _reauth(user: User, password: str) -> None:
    if not user.verify_password(password):
        raise HTTPException(status_code=403, detail="Password is incorrect")


def require_enrollment_code(user: User, supplied: Optional[str], request: Request) -> None:
    """Admins who must enrol a first factor need the out-of-band code, not just their password."""
    if not user.needs_mfa_setup:
        return
    ip = ratelimit.client_ip(request)
    ratelimit.check("login", ip, settings.RATE_LIMIT_LOGIN_FAILURES)
    if not mfa_service.enrollment_code_ok(user, supplied):
        ratelimit.hit("login", ip, settings.RATE_LIMIT_LOGIN_WINDOW_SECONDS)
        raise HTTPException(status_code=403, detail="A valid enrolment code is required. Ask a super admin or operator for one.")


# ---- login step 2 -----------------------------------------------------------

@router.post("/login/mfa")
async def login_mfa(request: Request, response: Response, body: MfaLogin, db: Session = Depends(get_db)):
    """Exchange (challenge token + TOTP/recovery code) for a session."""
    check_origin(request)
    ip = ratelimit.client_ip(request)
    ratelimit.check("login", ip, settings.RATE_LIMIT_LOGIN_FAILURES)
    invalid = HTTPException(status_code=401, detail="Invalid or expired code")

    ch = mfa_service.load_challenge(db, body.mfa_token)
    if ch is None:
        ratelimit.hit("login", ip, settings.RATE_LIMIT_LOGIN_WINDOW_SECONDS)
        raise invalid
    user = db.get(User, ch.user_id)
    if user is None or user.status != "active" or user.is_locked_out():
        mfa_service.burn_challenge(db, ch)
        ratelimit.hit("login", ip, settings.RATE_LIMIT_LOGIN_WINDOW_SECONDS)
        raise invalid

    method = mfa_service.verify_second_factor(db, user, body.code)
    if method is None:
        # Every wrong code counts against the challenge, the IP, and the account lockout.
        ch.attempts += 1
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= settings.MAX_LOGIN_ATTEMPTS:
            user.lockout_until = datetime.now(timezone.utc) + timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
            user.failed_login_attempts = 0
        record(db, AuditAction.MFA_CHALLENGE_FAILED, request, user, user.id, "user")
        db.commit()
        ratelimit.hit("login", ip, settings.RATE_LIMIT_LOGIN_WINDOW_SECONDS)
        logger.warning("mfa.challenge_failed", user_id=user.id)
        raise invalid

    db.delete(ch)
    if method == "recovery":
        record(
            db, AuditAction.MFA_RECOVERY_USED, request, user, user.id, "user",
            {"remaining": mfa_service.recovery_remaining(db, user)},
        )
    db.commit()
    return await complete_login(db, request, response, user, method=f"password+mfa_{method}")


# ---- self-service enrolment -------------------------------------------------

@router.get("/me/mfa")
def mfa_status(ctx=Depends(get_session_and_user), db: Session = Depends(get_db)):
    user = ctx[1]
    enabled = bool(user.mfa and user.mfa.enabled)
    return {
        "enabled": enabled,
        "pending": bool(user.mfa and not user.mfa.enabled),
        "recovery_codes_remaining": mfa_service.recovery_remaining(db, user) if enabled else 0,
    }


@router.post("/me/mfa/setup")
def mfa_setup(
    body: EnrolStart, request: Request, ctx=Depends(get_session_and_user), db: Session = Depends(get_db)
):
    """Start enrolment (requires the current password, plus an enrolment code for admins with no factor yet).
    Replaces any unconfirmed attempt."""
    user = ctx[1]
    _reauth(user, body.password)
    require_enrollment_code(user, body.enrollment_code, request)
    if user.mfa is not None and user.mfa.enabled:
        raise HTTPException(status_code=409, detail="MFA is already enabled")
    secret = mfa.new_secret()
    if user.mfa is None:
        db.add(UserMFA(user_id=user.id, secret_encrypted=mfa.encrypt_secret(secret), enabled=False))
    else:
        user.mfa.secret_encrypted = mfa.encrypt_secret(secret)
    db.commit()
    return {"secret": secret, "otpauth_uri": mfa.provisioning_uri(secret, user.email)}


@router.post("/me/mfa/enable")
def mfa_enable(body: CodeOnly, request: Request, ctx=Depends(get_session_and_user), db: Session = Depends(get_db)):
    """Confirm enrolment with a code from the authenticator app; returns recovery codes once."""
    session, user, _ = ctx
    if user.mfa is None or user.mfa.enabled:
        raise HTTPException(status_code=409, detail="No pending MFA setup")
    step = mfa.match_totp(mfa.decrypt_secret(user.mfa.secret_encrypted), body.code, None)
    if step is None:
        raise HTTPException(status_code=400, detail="Invalid code")
    user.mfa.enabled = True
    user.mfa.enabled_at = datetime.now(timezone.utc)
    user.mfa.last_used_step = step
    mfa_service.clear_enrollment_code(user)
    codes = mfa_service.replace_recovery_codes(db, user)
    revoked = revoke_user_sessions(db, user.id, except_id=session.id)
    record(db, AuditAction.MFA_ENABLED, request, user, user.id, "user", {"other_sessions_revoked": revoked})
    db.commit()
    return {"enabled": True, "recovery_codes": codes}


@router.post("/me/mfa/disable")
def mfa_disable(
    body: PasswordAndCode, request: Request, ctx=Depends(get_session_and_user), db: Session = Depends(get_db)
):
    session, user, _ = ctx
    _reauth(user, body.password)
    if user.mfa is None or not user.mfa.enabled:
        raise HTTPException(status_code=409, detail="MFA is not enabled")
    if mfa_service.verify_second_factor(db, user, body.code) is None:
        db.rollback()
        raise HTTPException(status_code=400, detail="Invalid code")
    mfa_service.remove_mfa(db, user)
    revoked = revoke_user_sessions(db, user.id, except_id=session.id)
    record(db, AuditAction.MFA_DISABLED, request, user, user.id, "user", {"other_sessions_revoked": revoked})
    db.commit()
    return {"enabled": False}


@router.post("/me/mfa/recovery-codes")
def mfa_regenerate(
    body: PasswordAndCode, request: Request, ctx=Depends(get_session_and_user), db: Session = Depends(get_db)
):
    user = ctx[1]
    _reauth(user, body.password)
    if user.mfa is None or not user.mfa.enabled:
        raise HTTPException(status_code=409, detail="MFA is not enabled")
    if mfa_service.verify_second_factor(db, user, body.code) is None:
        db.rollback()
        raise HTTPException(status_code=400, detail="Invalid code")
    codes = mfa_service.replace_recovery_codes(db, user)
    record(db, AuditAction.MFA_RECOVERY_REGENERATED, request, user, user.id, "user")
    db.commit()
    return {"recovery_codes": codes}


# ---- admin: lost device -----------------------------------------------------

@router.post("/admin/users/{user_id}/mfa/reset")
def admin_reset_mfa(
    user_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)
):
    """Remove all of a user's extra sign-in factors: TOTP, recovery codes and passkeys, and lift
    the passkey-required policy (lost device). Same target protections as other admin actions."""
    user = _get_or_404(db, user_id)
    _guard_target(actor, user)
    if user.id == actor.id:
        raise HTTPException(status_code=400, detail="Use the account security page to manage your own MFA")
    if user.mfa is None and not user.passkeys and not user.passkey_required:
        raise HTTPException(status_code=409, detail="User has no MFA or passkeys configured")
    result = mfa_service.reset_all_factors(db, user)
    record(db, AuditAction.MFA_RESET, request, actor, user.id, "user", result)
    db.commit()
    return {"success": True}


@router.post("/admin/users/{user_id}/enrollment-code")
def issue_enrollment_code(
    user_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)
):
    """A super admin hands an admin the one-time code they need to enrol their first factor.
    A super admin's own code comes from the operator CLI (nobody above them)."""
    if not actor.is_super_admin:
        raise HTTPException(status_code=403, detail="Forbidden")
    user = _get_or_404(db, user_id)
    if not user.is_admin or user.is_super_admin:
        raise HTTPException(status_code=400, detail="Enrolment codes are for administrators")
    if not user.needs_mfa_setup:
        raise HTTPException(status_code=409, detail="This user does not need to enrol a first factor")
    code = mfa_service.issue_enrollment_code(user)
    record(
        db, AuditAction.ENROLLMENT_CODE_ISSUED, request, actor, user.id, "user",
        {"expires_in_hours": mfa_service.ENROLLMENT_CODE_HOURS},
    )
    db.commit()
    return {"code": code, "expires_in_hours": mfa_service.ENROLLMENT_CODE_HOURS}
