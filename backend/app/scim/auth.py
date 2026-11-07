"""SCIM bearer-token authentication (ADR 007 D1).

The tenant comes from the token and nowhere else. A request with no valid token never gets a tenant-scoped session
(fail closed). All token failures look identical to the caller.
"""

import hashlib
import hmac
import ipaddress
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import structlog
from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from backend.app import ratelimit
from backend.app.audit.model import AuditAction, AuditEvent
from backend.app.config import settings
from backend.app.db import SessionLocal
from backend.app.scim.errors import ScimError
from backend.app.scim.models import ScimToken
from backend.app.tenancy import unscoped, use_tenant

logger = structlog.get_logger(__name__)

TOKEN_PREFIX = "idf_scim_"
_MAX_TOKEN_LEN = 128
_TOUCH_INTERVAL = timedelta(seconds=60)


def new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_token(raw: str) -> str:
    """Keyed hash (HMAC-SHA256 with SECRET_KEY): a database leak alone cannot confirm a guessed token."""
    return hmac.new(settings.SECRET_KEY.encode(), b"scim-token:" + raw.encode(), hashlib.sha256).hexdigest()


def audit(db: Session, action: AuditAction, request: Optional[Request], token: Optional[ScimToken],
          target_id: Any = None, target_type: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> None:
    """Stage an audit event whose actor is the SCIM token (never the token value)."""
    db.add(AuditEvent(
        action=action,
        actor_id=str(token.id) if token else None,
        actor_type="scim_token" if token else None,
        actor_ip_address=request.client.host if request and request.client else None,
        target_id=str(target_id) if target_id is not None else None,
        target_type=target_type,
        metadata=metadata or None,
    ))


def _unauthorized() -> ScimError:
    return ScimError(401, "Authentication required", None, {"WWW-Authenticate": "Bearer"})


def ip_permitted(token: ScimToken, ip: str) -> bool:
    """No list = any address. A malformed peer address never matches a non-empty list (fail closed)."""
    nets = token.allowed_cidrs or []
    if not nets:
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in ipaddress.ip_network(n, strict=False) for n in nets)


_READ_METHODS = ("GET", "HEAD")


def scope_violation(token: ScimToken, method: str, path: str) -> Optional[str]:
    rel = path.split("/scim/v2", 1)[-1].lstrip("/")
    if token.read_only and method.upper() not in _READ_METHODS:
        return "This token is read-only"
    if token.users_only and rel.split("/", 1)[0].lower().split(".")[0] == "groups":
        return "This token may only access Users"
    return None


class Ctx:
    def __init__(self, db: Session, token: ScimToken, request: Request):
        self.db, self.token, self.request = db, token, request


def _fail(request: Request, db: Session, token: Optional[ScimToken], reason: str) -> ScimError:
    ip = ratelimit.client_ip(request)
    ratelimit.hit("scim_auth_fail", ip, settings.SCIM_RATE_LIMIT_WINDOW_SECONDS)
    if token is not None:
        try:
            use_tenant(db, token.tenant_id)
            audit(db, AuditAction.SCIM_AUTH_FAILED, request, token, token.id, "scim_token", {"reason": reason})
            db.commit()
        except Exception:  # noqa: BLE001 - never let auditing change the response
            db.rollback()
    logger.warning("scim.auth_failed", reason=reason, ip=ip)  # no token, no headers
    return _unauthorized()


def get_ctx(request: Request):
    """FastAPI dependency: authenticates, binds the tenant, yields a context, always closes the session."""
    ratelimit.check("scim_auth_fail", ratelimit.client_ip(request), settings.SCIM_RATE_LIMIT_FAILURES)
    db = SessionLocal()  # deliberately no tenant yet
    try:
        header = request.headers.get("authorization", "")
        scheme, _, raw = header.partition(" ")
        raw = raw.strip()
        if scheme.lower() != "bearer" or not raw or len(raw) > _MAX_TOKEN_LEN or not raw.startswith(TOKEN_PREFIX):
            raise _fail(request, db, None, "missing_or_malformed")
        digest = hash_token(raw)
        with unscoped(db):
            token = db.query(ScimToken).filter(ScimToken.token_hash == digest).first()
        if token is None or not hmac.compare_digest(token.token_hash, digest):
            raise _fail(request, db, None, "unknown_token")
        if token.revoked_at is not None:
            raise _fail(request, db, token, "revoked")
        now = datetime.now(timezone.utc)
        if token.expires_at is not None and token.expires_at <= now:
            raise _fail(request, db, token, "expired")
        use_tenant(db, token.tenant_id)
        if not ip_permitted(token, ratelimit.client_ip(request)):
            raise _fail(request, db, token, "ip_not_allowed")
        denied = scope_violation(token, request.method, request.url.path)
        if denied:
            try:
                audit(db, AuditAction.SCIM_AUTH_FAILED, request, token, token.id, "scim_token", {"reason": "scope", "method": request.method})
                db.commit()
            except Exception:  # noqa: BLE001
                db.rollback()
            raise ScimError(403, denied)
        try:
            ratelimit.check("scim_req", str(token.id), settings.SCIM_RATE_LIMIT_REQUESTS_PER_MINUTE)
        except HTTPException:
            raise
        ratelimit.hit("scim_req", str(token.id), 60)
        if token.last_used_at is None or now - token.last_used_at > _TOUCH_INTERVAL:
            token.last_used_at = now
            db.commit()
        yield Ctx(db, token, request)
    finally:
        db.close()
