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


def set_session_cookie(response: Response, raw_token: str, lifetime_hours: Optional[int] = None) -> None:
    """Set the opaque session cookie (HttpOnly, SameSite, Secure per config)."""
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=raw_token,
        max_age=(lifetime_hours or settings.SESSION_LIFETIME_HOURS) * 3600,
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
    """Resolve the session cookie to (session, user, raw_token) or raise 401. An admin API token (Bearer idf_api_...) is accepted on /admin/** only."""
    from backend.app.api_tokens import service as api_tokens

    if api_tokens.is_api_token_request(request):
        return api_tokens.authenticate(request, db)
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

    from backend.app.security_policy import service as sec_policy

    pol = sec_policy.get(db)  # read at every request, so a tightened policy applies to sessions already open
    now = datetime.now(timezone.utc)
    idle = timedelta(minutes=pol.idle_timeout_minutes)
    if now - session.last_activity_at > idle or now - session.created_at > timedelta(hours=pol.session_lifetime_hours):
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


def require_admin(request: Request, ctx=Depends(get_session_and_user), db: Session = Depends(get_db)) -> User:
    """Deny by default: only admins pass, in a session that is in admin view, and only for what their administrator roles allow."""
    session, user, _ = ctx
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Forbidden")
    if session.acting_as_user:
        # The admin chose "user view" for this session: administrator functions are off until they step back up.
        raise HTTPException(status_code=403, detail="Switch to admin view to use administrator functions")
    if user.needs_mfa_setup:
        # Still signed in (so they can reach Account settings and enrol), but no admin power yet.
        raise HTTPException(status_code=403, detail="Multi-factor authentication setup required")
    token = getattr(session, "api_token", None)
    if token is not None and token.read_only and request.method not in SAFE_METHODS:
        raise HTTPException(status_code=403, detail="This API token is read-only")
    if not user.is_super_admin:
        from backend.app.admin_roles import permissions
        from backend.app.admin_roles.resolve import roles_of

        route = request.scope.get("route")
        template = getattr(route, "path", "") or request.url.path
        template = template[len("/api/v1"):] if template.startswith("/api/v1") else template
        roles = roles_of(db, user.id)  # direct roles plus those carried by the user's groups
        if not permissions.allowed(roles, request.method, template):
            raise HTTPException(status_code=403, detail="Your administrator role does not allow this")
    return user


def require_admin_session(ctx=Depends(get_session_and_user)) -> User:
    """An administrator signed in with a browser session (never an API token): used to manage API tokens themselves."""
    session, user, _ = ctx
    if getattr(session, "api_token", None) is not None or not user.is_admin or session.acting_as_user or user.needs_mfa_setup:
        raise HTTPException(status_code=403, detail="Forbidden")
    return user
