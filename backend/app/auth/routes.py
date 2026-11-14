"""Authentication API routes.

Implements secure login, logout, and bootstrap endpoints.
Follows security best practices for session management.
"""

import hmac
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from backend.app import passwords, ratelimit
from backend.app.auth import mfa_service
from backend.app.auth.authn import acr_for, amr_for
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
    if action in (AuditAction.LOGIN_SUCCESS, AuditAction.LOGOUT) and actor_id is not None:
        from backend.app.recipes.events import emit_from_audit

        emit_from_audit(db, action, None, int(actor_id), "user", metadata)  # same commit as the audit row
    db.commit()


def _session_info(session: AuthSession) -> dict:
    return {
        "expires_at": session.expires_at.isoformat(),
        "auth_time": session.auth_time.isoformat(),
        "amr": session.amr,
        "acr": acr_for(session.amr),
    }


_KNOWN_IP_DAYS, _KNOWN_IP_MAX = 30, 20


def remember_ip(user_id: int, ip: str) -> None:
    """Note an address this person has signed in from (kept 30 days). Best effort: Redis trouble must not block sign-in."""
    try:
        r, key = ratelimit._redis(), f"kip:{user_id}"
        if r.scard(key) < _KNOWN_IP_MAX:
            r.sadd(key, ip)
        r.expire(key, _KNOWN_IP_DAYS * 86400)
    except Exception:  # noqa: BLE001
        logger.warning("login.known_ip_unavailable")


def is_known_ip(user_id: int, ip: str) -> bool:
    try:
        return bool(ratelimit._redis().sismember(f"kip:{user_id}", ip))
    except Exception:  # noqa: BLE001
        return False


async def complete_login(db: Session, request: Request, response: Response, user: User, method: str) -> dict:
    """Create the session + cookie for a fully authenticated user (password, and MFA if enrolled)."""
    now = datetime.now(timezone.utc)
    user.failed_login_attempts = 0
    user.lockout_until = None
    user.last_login_at = now
    if request.client:
        remember_ip(user.id, request.client.host)

    from backend.app.security_policy import service as sec_policy

    lifetime = sec_policy.get(db).session_lifetime_hours
    session = AuthSession.create(
        user_id=user.id,
        session_lifetime_hours=lifetime,
        ip_address=request.client.host if request.client else None,
        user_agent=(request.headers.get("user-agent") or "")[:500],
        is_admin_session=user.is_admin,
        amr=amr_for(method),
    )
    db.add(session)
    db.commit()

    set_session_cookie(response, session.raw_token, lifetime)

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
        "session": _session_info(session),
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
        passwords.burn(login_data.password)  # same cost as a real check: no account enumeration by timing
        logger.warning("login.attempt_failed", reason="user_not_found")
        raise fail()

    # Anyone can type wrong passwords for someone else's email and lock them out. So a locked account still lets the
    # owner in from an address they have signed in from recently; everywhere else the lockout holds.
    if user.is_locked_out() and not is_known_ip(user.id, ip):
        passwords.burn(login_data.password)  # equalise timing
        logger.warning("login.attempt_failed", reason="account_locked", user_id=user.id)
        raise fail()

    if not user.verify_password(login_data.password):
        if user.is_locked_out():  # known address during a lockout: refuse, but do not extend the lockout
            logger.warning("login.attempt_failed", reason="invalid_password_while_locked", user_id=user.id)
            raise fail()
        user.failed_login_attempts += 1
        from backend.app.recipes import events as recipe_events

        recipe_events.emit_login_failed(db, user, user.failed_login_attempts)  # outbox row commits with the counter
        from backend.app.security_policy import service as sec_policy

        pol = sec_policy.get(db)
        if user.failed_login_attempts >= pol.max_failed_attempts:
            user.lockout_until = now + timedelta(minutes=pol.lockout_minutes)
            user.failed_login_attempts = 0
        db.commit()
        await log_audit(
            db, AuditAction.LOGIN_FAILURE, actor_id=str(user.id), request=request
        )
        logger.warning("login.attempt_failed", reason="invalid_password", user_id=user.id)
        raise fail()

    if user.password_needs_rehash():  # hashed with older Argon2 parameters: upgrade now that the password is known
        user.password_hash = passwords.hash_password(login_data.password)  # not a password change: password_changed_at stays
        db.commit()

    if user.status == "active":
        from backend.app.security_policy import service as sec_policy

        if sec_policy.expired_by_age(sec_policy.get(db), user):
            user.status = "password_expired"  # the organization's maximum password age has passed
            db.commit()
            await log_audit(db, AuditAction.PASSWORD_EXPIRED_BY_POLICY, actor_id=str(user.id), request=request)

    if user.status == "password_expired":
        # Only someone who already knows the password learns this; the UI then offers the change-password form.
        return {"success": False, "password_change_required": True}

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
        "session": _session_info(session),
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

    from backend.app.security_policy import service as sec_policy

    # The first administrator is held to the same password policy as everyone else.
    sec_policy.validate_new(db, bootstrap_data.password, email=bootstrap_data.email, first=bootstrap_data.first_name, last=bootstrap_data.last_name)

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