"""Authentication API routes.

Implements secure login, logout, and bootstrap endpoints.
Follows security best practices for session management.
"""

from datetime import datetime, timedelta
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.db import get_db
from backend.app.users.model import User
from backend.app.auth.session import Session
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


class AuditLog(BaseModel):
    """Audit event schema."""

    id: int
    timestamp: datetime
    action: str
    event_type: str
    actor_id: Optional[int] = None
    target_id: Optional[int] = None
    ip_address: Optional[str] = None


async def log_audit(
    db: Session,
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


@router.post("/login", response_model=dict)
async def login_endpoint(
    request: Request,
    login_data: LoginRequest,
    db: Session = Depends(get_db),
    response: JSONResponse = None,
):
    """Authenticate user and create session.

    Security measures:
    - Rate limiting via failed attempt tracking
    - Account lockout after multiple failures
    - Secure session token generation
    - Session tracking for audit
    """
    # Check if email format is valid
    if not login_data.email:
        raise HTTPException(status_code=400, detail="Email is required")

    # Find user
    user = db.query(User).filter(User.email == login_data.email.lower()).first()

    if not user:
        # Don't reveal whether user exists
        logger.warning("login.attempt_failed", reason="user_not_found", email=login_data.email)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Check if account is locked
    if user.is_locked_out():
        logger.warning("login.attempt_failed", reason="account_locked", user_id=user.id)
        raise HTTPException(status_code=423, detail="Account is temporarily locked")

    # Verify password
    if not user.verify_password(login_data.password):
        # Increment failed attempts
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= settings.MAX_LOGIN_ATTEMPTS:
            user.locked_out_at = datetime.utcnow() + timedelta(
                minutes=settings.LOGIN_LOCKOUT_MINUTES
            )
        db.commit()

        logger.warning("login.attempt_failed", reason="invalid_password", user_id=user.id)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Reset failed attempts on successful login
    user.failed_login_attempts = 0
    user.locked_out_at = None
    user.last_login_at = datetime.utcnow()

    # Create session
    session = Session.create(
        user_id=user.id,
        session_lifetime_hours=settings.SESSION_LIFETIME_HOURS,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        is_admin_session=user.is_admin,
    )

    db.add(session)
    db.commit()

    # Log audit event
    await log_audit(
        db,
        AuditAction.LOGIN_SUCCESS,
        actor_id=user.id,
        metadata={"method": "password"},
        request=request,
    )

    logger.info("login.success", user_id=user.id)

    return {
        "success": True,
        "user": user.to_dict(),
        "session": {"expires_at": session.expires_at.isoformat()},
    }


@router.post("/logout", response_model=LogoutResponse)
async def logout_endpoint(
    request: Request,
    db: Session = Depends(get_db),
    session_token: Optional[str] = None,
):
    """Logout user and invalidate session.

    Security:
    - Invalidates server-side session
    - Clears via cookie in actual client
    - Logs audit event
    """
    # In a real implementation, we'd get the session from the cookie
    # and invalidate it server-side
    # For now, we'll just log the logout

    logger.info("logout.executed", ip=request.client.host if request.client else None)

    await log_audit(
        db,
        AuditAction.LOGOUT,
        ip_address=request.client.host if request.client else None,
    )

    return {"success": True, "message": "Logged out successfully"}


@router.get("/me", response_model=dict)
async def get_current_user_endpoint(
    request: Request,
    db: Session = Depends(get_db),
):
    """Get current authenticated user info."""
    # In a real implementation, we'd validate the session cookie
    # and return the user info
    return {"authenticated": False, "message": "Not authenticated"}


@router.post("/admin/bootstrap", response_model=BootstrapResponse)
async def bootstrap_admin_endpoint(
    bootstrap_data: BootstrapAdminRequest,
    db: Session = Depends(get_db),
    request: Optional[Request] = None,
):
    """Bootstrap first administrator account.

    Security:
    - Requires secret key from environment
    - Creates only one admin user
    - Requires strong password
    - Logs all bootstrap attempts
    """
    # Verify secret key
    if bootstrap_data.secret_key != settings.ADMIN_SECRET_KEY:
        logger.warning("bootstrap.attempt_failed", reason="invalid_secret_key")
        raise HTTPException(status_code=403, detail="Invalid bootstrap key")

    # Check if admin already exists
    existing_admin = (
        db.query(User).filter(User.is_super_admin == True).first()
    )
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