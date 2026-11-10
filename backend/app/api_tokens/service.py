"""Bearer authentication with an admin API token (ADR 024).

Accepted only on /admin/** and never on /admin/api-tokens/** (a token cannot mint or manage tokens). The token acts as its owner, so
the owner's current administrator roles, MFA policy and account status apply on every call; read_only narrows it further.
"""

import hashlib
import hmac
import ipaddress
import secrets
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Optional

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from backend.app import ratelimit
from backend.app.api_tokens.models import ApiToken
from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.config import settings
from backend.app.users.model import User

TOKEN_PREFIX = "idf_api_"
MAX_TOKEN_LEN = 128
DEFAULT_DAYS, MAX_DAYS = 30, 90
MAX_ACTIVE_PER_USER = 10
_TOUCH_INTERVAL = timedelta(seconds=60)
_SAFE = ("GET", "HEAD", "OPTIONS")


def new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_token(raw: str) -> str:
    """Keyed hash (HMAC-SHA256 with SECRET_KEY, domain-separated from SCIM tokens)."""
    return hmac.new(settings.SECRET_KEY.encode(), b"api-token:" + raw.encode(), hashlib.sha256).hexdigest()


def is_api_token_request(request: Request) -> bool:
    return request.headers.get("authorization", "")[:7].lower() == "bearer " and request.headers["authorization"][7:].strip().startswith(TOKEN_PREFIX)


def ip_permitted(token: ApiToken, ip: str) -> bool:
    nets = token.allowed_cidrs or []
    if not nets:
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in ipaddress.ip_network(n, strict=False) for n in nets)


def _deny(request: Request, db: Session, token: Optional[ApiToken], reason: str, status: int = 401) -> HTTPException:
    ip = ratelimit.client_ip(request)
    ratelimit.hit("api_token_fail", ip, settings.SCIM_RATE_LIMIT_WINDOW_SECONDS)
    if token is not None:
        try:
            owner = db.get(User, token.user_id)
            record(db, AuditAction.API_TOKEN_AUTH_FAILED, request, owner, token.id, "api_token", {"reason": reason, "name": token.name, "ip": ip})
            db.commit()
        except Exception:  # noqa: BLE001 - auditing must never change the answer
            db.rollback()
    return HTTPException(status_code=status, detail="Not authenticated", headers={"WWW-Authenticate": "Bearer"})


def authenticate(request: Request, db: Session):
    """-> (session-like, user, raw). Raises 401/403."""
    ip = ratelimit.client_ip(request)
    ratelimit.check("api_token_fail", ip, settings.SCIM_RATE_LIMIT_FAILURES)
    path = request.url.path
    if not path.startswith("/api/v1/admin/") or path.startswith("/api/v1/admin/api-tokens"):
        raise HTTPException(status_code=403, detail="API tokens cannot be used for this endpoint")
    raw = request.headers["authorization"][7:].strip()
    if len(raw) > MAX_TOKEN_LEN:
        raise _deny(request, db, None, "malformed")
    digest = hash_token(raw)
    token = db.query(ApiToken).filter(ApiToken.token_hash == digest).first()
    if token is None or not hmac.compare_digest(token.token_hash, digest):
        raise _deny(request, db, None, "unknown_token")
    if token.revoked_at is not None:
        raise _deny(request, db, token, "revoked")
    now = datetime.now(timezone.utc)
    if token.expires_at <= now:
        raise _deny(request, db, token, "expired")
    user = db.get(User, token.user_id)
    if user is None or user.status != "active":
        raise _deny(request, db, token, "owner_inactive")
    if not ip_permitted(token, ip):
        raise _deny(request, db, token, "ip_not_allowed")
    if token.read_only and request.method.upper() not in _SAFE:
        record(db, AuditAction.API_TOKEN_AUTH_FAILED, request, user, token.id, "api_token", {"reason": "read_only", "method": request.method, "name": token.name})
        db.commit()
        raise HTTPException(status_code=403, detail="This API token is read-only")
    if token.last_used_at is None or now - token.last_used_at > _TOUCH_INTERVAL or token.last_used_ip != ip:
        if token.last_used_ip and token.last_used_ip != ip:
            record(db, AuditAction.API_TOKEN_NEW_IP, request, user, token.id, "api_token", {"name": token.name, "ip": ip, "previous_ip": token.last_used_ip})
        token.last_used_at, token.last_used_ip = now, ip
        db.commit()
    # Looks like a session to require_admin: never acting as a plain user, and carrying the token for audit and scope.
    return SimpleNamespace(id=None, acting_as_user=False, api_token=token), user, raw
