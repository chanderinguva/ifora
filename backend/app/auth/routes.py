"""Authentication API routes.

Implements secure login, logout, and bootstrap endpoints.
Follows security best practices for session management.
"""

import hmac
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from passlib.hash import argon2
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from backend.app import ratelimit
from backend.app.auth import mfa_service
from backend.app.config import settings
from backend.app.db import get_db
from backend.app.users.model import User
from backend.app.auth.session import Session as AuthSession
from backend.app.auth.deps import (
    check_origin,
    clear_session_cookie,
    get_session_and_user,
    set_session_cookie,
)
from backend.app.audit.model import AuditEvent, AuditAction

logger = structlog.get_logger(__name__)

router = APIRouter()


# Schemas
class LoginRequest(BaseModel):
    """Login request schema."""

    email: EmailStr = Field(..., description="User email")
    password: str = Field(..., min_length=1, description="User password")


class BootstrapAdminRequest(BaseModel):
    """Bootstrap admin request schema."""

    email: EmailStr = Field(..., description="Admin email")
    password: str = Field(..., min_length=8, description="Admin password")
    first_name: str = Field(..., min_length=1, max_length=100, description="First name")
    last_name: str = Field(..., min_length=1, max_length=100, description="Last name")
    secret_key: str = Field(..., description="Bootstrap secret key")


class BootstrapResponse(BaseModel):
    """Bootstrap response schema."""

    success: bool = True
    message: str = "Administrator account created"


class LogoutResponse(BaseModel):
    """Logout response schema."""

    success: bool = True
    message: str = "Logged out successfully"


async def log_audit(
    db,
    action: AuditAction,
    actor_id: Optional[int] = None,
    target_id: Optional[int] = None,
    metadata: Optional[dict] = None,
    request: Optional[Request] = None,
) -> None:
    """Log audit event to database."""
    audit_event = AuditEvent(
        action=action,
        actor_id=actor_id,
        target_id=target_id,
        actor_ip_address=request.client.host if request and request.client else None,
        metadata=metadata,
    )
    db.add(audit_event)
    db.commit()


# Verified against when the account does not exist, so response time does not
# reveal whether an email is registered (account enumeration resistance).
_DUMMY_HASH = argon2.hash("dummy-password-for-timing-equalisation")


async def complete_login(db: Session, request: Request, response: Response, user: User, method: str) -> dict:
    """Create the session + cookie for a fully authenticated user (password, and MFA if enrolled)."""
    now = datetime.now(timezone.utc)
    user.failed_login_attempts = 0
    user.lockout_until = None
    user.last_login_at = now

    session = AuthSession.create(
        user_id=user.id,
        session_lifetime_hours=settings.SESSION_LIFETIME_HOURS,
        ip_address=request.client.host if request.client else None,
        user_agent=(request.headers.get("user-agent") or "")[:500],
        is_admin_session=user.is_admin,
    )
    db.add(session)
    db.commit()

    set_session_cookie(response, session.raw_token)

    await log_audit(
        db,
        AuditAction.LOGIN_SUCCESS,
        actor_id=str(user.id),
        metadata={"method": method},
        request=request,
    )
    logger.info("login.success", user_id=user.id)

    return {
        "success": True,
        "user": user.to_dict(),
        "csrf_token": AuthSession.csrf_token_for(session.raw_token),
        "session": {"expires_at": session.expires_at.isoformat()},
    }


@router.post("/login", response_model=dict)
async def login_endpoint(
    request: Request,
    response: Response,
    login_data: LoginRequest,
    db: Session = Depends(get_db),
):
    """Authenticate user, create a session and set the session cookie.

    Security measures:
    - Origin check (login CSRF)
    - Uniform 401 for unknown user / bad password / locked / inactive account
    - Constant-ish timing for unknown users
    - Account lockout after repeated failures
    - Fresh opaque token per login (no session fixation); only its hash is stored
    """
    check_origin(request)
    ip = ratelimit.client_ip(request)
    ratelimit.check("login", ip, settings.RATE_LIMIT_LOGIN_FAILURES)
    now = datetime.now(timezone.utc)
    invalid = HTTPException(status_code=401, detail="Invalid credentials")

    def fail() -> HTTPException:
        ratelimit.hit("login", ip, settings.RATE_LIMIT_LOGIN_WINDOW_SECONDS)
        return invalid

    user = db.query(User).filter(User.email == login_data.email.lower()).first()

    if not user:
        try:
            argon2.verify(login_data.password, _DUMMY_HASH)
        except Exception:
            pass
        logger.warning("login.attempt_failed", reason="user_not_found")
        raise fail()

    if user.is_locked_out():
        try:
            argon2.verify(login_data.password, _DUMMY_HASH)  # equalise timing
        except Exception:
            pass
        logger.warning("login.attempt_failed", reason="account_locked", user_id=user.id)
        raise fail()

    if not user.verify_password(login_data.password):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= settings.MAX_LOGIN_ATTEMPTS:
            user.lockout_until = now + timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
            user.failed_login_attempts = 0
        db.commit()
        await log_audit(
            db, AuditAction.LOGIN_FAILURE, actor_id=str(user.id), request=request
        )
        logger.warning("login.attempt_failed", reason="invalid_password", user_id=user.id)
        raise fail()

    if user.status != "active":
        logger.warning("login.attempt_failed", reason="inactive", user_id=user.id)
        raise fail()

    if user.passkey_required:
        # Phishing-resistant policy: a password (even with TOTP) can never start a session.
        # Only someone who already knows the password learns this.
        logger.info("login.refused_passkey_required", user_id=user.id)
        raise HTTPException(status_code=403, detail="This account requires signing in with a passkey.")

    if user.mfa is not None and user.mfa.enabled:
        # Password was right, but no session until the second factor is proven.
        raw = mfa_service.issue_challenge(db, user)
        return {
            "success": False,
            "mfa_required": True,
            "mfa_token": raw,
            "expires_in": settings.MFA_CHALLENGE_MINUTES * 60,
        }

    return await complete_login(db, request, response, user, method="password")


@router.post("/logout", response_model=LogoutResponse)
async def logout_endpoint(
    request: Request,
    response: Response,
    ctx=Depends(get_session_and_user),
    db: Session = Depends(get_db),
):
    """Revoke the server-side session and clear the cookie (CSRF-protected)."""
    session, user, _ = ctx
    session.revoke()
    db.commit()
    clear_session_cookie(response)
    await log_audit(db, AuditAction.LOGOUT, actor_id=str(user.id), request=request)
    logger.info("logout.executed", user_id=user.id)
    return {"success": True, "message": "Logged out successfully"}


@router.get("/me")
async def get_current_user_endpoint(ctx=Depends(get_session_and_user)):
    """Return the authenticated user plus the CSRF token for this session."""
    session, user, raw_token = ctx
    return {
        "authenticated": True,
        "user": {**user.to_dict(), "acting_as_user": session.acting_as_user},
        "csrf_token": AuthSession.csrf_token_for(raw_token),
        "session": {"expires_at": session.expires_at.isoformat()},
    }


@router.post("/admin/bootstrap", response_model=BootstrapResponse)
async def bootstrap_admin_endpoint(
    bootstrap_data: BootstrapAdminRequest,
    db: Session = Depends(get_db),
    request: Request = None,
):
    """Bootstrap first administrator account.

    Security:
    - Requires secret key from environment
    - Creates only one admin user
    - Requires strong password
    - Logs all bootstrap attempts
    """
    ip = ratelimit.client_ip(request) if request else "unknown"
    ratelimit.check("bootstrap", ip, settings.RATE_LIMIT_BOOTSTRAP_ATTEMPTS)
    # Verify secret key
    if not hmac.compare_digest(
        bootstrap_data.secret_key.encode(), settings.ADMIN_SECRET_KEY.encode()
    ):
        ratelimit.hit("bootstrap", ip, settings.RATE_LIMIT_BOOTSTRAP_WINDOW_SECONDS)
        logger.warning("bootstrap.attempt_failed", reason="invalid_secret_key")
        raise HTTPException(status_code=403, detail="Invalid bootstrap key")

    # Check if admin already exists
    existing_admin = db.query(User).filter(User.is_super_admin == True).first()
    if existing_admin:
        logger.warning("bootstrap.attempt_failed", reason="admin_already_exists")
        raise HTTPException(status_code=409, detail="Administrator already exists")

    # Check if email is already used
    existing_user = db.query(User).filter(User.email == bootstrap_data.email.lower()).first()
    if existing_user:
        logger.warning("bootstrap.attempt_failed", reason="email_in_use", email=bootstrap_data.email)
        raise HTTPException(status_code=409, detail="Email already in use")

    # Create super admin user
    user = User(
        email=bootstrap_data.email,
        username=bootstrap_data.email.split("@")[0],
        first_name=bootstrap_data.first_name,
        last_name=bootstrap_data.last_name,
        password=bootstrap_data.password,
        is_admin=True,
        is_super_admin=True,
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    # Log audit event
    await log_audit(
        db,
        AuditAction.ADMIN_BOOTSTRAP,
        target_id=user.id,
        metadata={"ip": request.client.host if request and request.client else None},
        request=request,
    )

    logger.info("bootstrap.success", user_id=user.id, email=user.email)

    return {"success": True, "message": "Administrator account created"}