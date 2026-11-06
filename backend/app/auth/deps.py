"""Authentication dependencies: session cookie lookup and CSRF protection."""

import hmac
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from backend.app.auth.session import Session as AuthSession
from backend.app.auth.session import SessionStatus
from backend.app.config import settings
from backend.app.db import get_db
from backend.app.users.model import User

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def set_session_cookie(response: Response, raw_token: str) -> None:
    """Set the opaque session cookie (HttpOnly, SameSite, Secure per config)."""
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=raw_token,
        max_age=settings.SESSION_LIFETIME_HOURS * 3600,
        path="/",
        httponly=True,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite=settings.SESSION_COOKIE_SAMESITE,
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite=settings.SESSION_COOKIE_SAMESITE,
    )


def check_origin(request: Request) -> None:
    """Reject state-changing requests from untrusted origins.

    Browsers always send Origin on cross-origin POSTs; if present it must be
    allow-listed. Defends login CSRF where no session exists yet.
    """
    if request.method in SAFE_METHODS:
        return
    origin = request.headers.get("origin")
    if origin is not None and origin not in settings.CORS_ORIGINS:
        raise HTTPException(status_code=403, detail="Origin not allowed")


def get_session_and_user(
    request: Request, db: Session = Depends(get_db)
) -> Tuple[AuthSession, User, str]:
    """Resolve the session cookie to (session, user, raw_token) or raise 401."""
    raw_token: Optional[str] = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not raw_token or len(raw_token) > 128:
        raise HTTPException(status_code=401, detail="Not authenticated")

    session = (
        db.query(AuthSession)
        .filter(AuthSession.token == AuthSession.hash_token(raw_token))
        .first()
    )
    if session is None or session.is_expired:
        if session is not None and session.status == SessionStatus.ACTIVE.value:
            session.status = SessionStatus.EXPIRED.value
            db.commit()
        raise HTTPException(status_code=401, detail="Not authenticated")

    idle = timedelta(minutes=settings.SESSION_IDLE_TIMEOUT_MINUTES)
    if datetime.now(timezone.utc) - session.last_activity_at > idle:
        session.status = SessionStatus.EXPIRED.value
        db.commit()
        raise HTTPException(status_code=401, detail="Not authenticated")

    user = db.query(User).filter(User.id == session.user_id).first()
    if user is None or user.status != "active":
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Unsafe methods need Origin check + CSRF token bound to this session.
    if request.method not in SAFE_METHODS:
        check_origin(request)
        supplied = request.headers.get("x-csrf-token", "")
        expected = AuthSession.csrf_token_for(raw_token)
        if not hmac.compare_digest(supplied, expected):
            raise HTTPException(status_code=403, detail="Invalid CSRF token")

    session.touch()
    db.commit()
    return session, user, raw_token


def get_current_user(ctx=Depends(get_session_and_user)) -> User:
    return ctx[1]


def require_admin(user: User = Depends(get_current_user)) -> User:
    """Deny by default: only admins pass."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Forbidden")
    if user.needs_mfa_setup:
        # Still signed in (so they can reach Account settings and enrol), but no admin power yet.
        raise HTTPException(status_code=403, detail="Multi-factor authentication setup required")
    return user
