"""Sign in with a Cloudflare Access identity token (demo environments; off unless ACCESS_SSO_ENABLED).

Cloudflare Access authenticates the visitor (one-time PIN to an invited email) and forwards a signed JWT in
`Cf-Access-Jwt-Assertion`. We verify it ourselves: signature against the team's published keys, issuer, audience and
expiry. The token is the only thing trusted; no other header or cookie is read. Administrators, accounts with a second
factor, and accounts that require a passkey are never signed in this way: they keep the stronger path.
"""

import re
import threading
import time
from typing import Optional

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet
from joserfc.jwt import JWTClaimsRegistry
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app import ratelimit
from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.auth.authn import amr_for
from backend.app.auth.deps import check_origin, get_session_and_user
from backend.app.auth.routes import complete_login
from backend.app.auth.sessions_util import revoke_user_sessions
from backend.app.config import settings
from backend.app.db import get_db
from backend.app.users.model import User

logger = structlog.get_logger(__name__)
router = APIRouter()

HEADER = "Cf-Access-Jwt-Assertion"
METHOD = "access"
_JWKS_TTL = 600
_MIN_REFETCH_SECONDS = 60


class AccessTokenError(Exception):
    """The identity token is missing, malformed, unsigned by Access, for another application, or expired."""


# --- keys -----------------------------------------------------------------------------------------------------

def _fetch_jwks() -> dict:
    """The team's public keys. Replaced in tests."""
    r = httpx.get(f"https://{settings.ACCESS_TEAM_DOMAIN}/cdn-cgi/access/certs", timeout=5.0)
    r.raise_for_status()
    return r.json()


_lock = threading.Lock()
_cache: dict = {"keys": None, "at": 0.0, "tried": 0.0}


def reset_cache() -> None:
    with _lock:
        _cache.update(keys=None, at=0.0, tried=0.0)


def _keyset(force: bool = False) -> KeySet:
    with _lock:
        now = time.monotonic()
        fresh = _cache["keys"] is not None and now - _cache["at"] < _JWKS_TTL
        if fresh and not force:
            return _cache["keys"]
        if force and now - _cache["tried"] < _MIN_REFETCH_SECONDS and _cache["keys"] is not None:
            return _cache["keys"]  # do not let a stream of unknown key ids turn into a stream of fetches
        _cache["tried"] = now
        try:
            _cache["keys"] = KeySet.import_key_set({"keys": _fetch_jwks()["keys"]})
            _cache["at"] = now
        except Exception as e:  # noqa: BLE001
            logger.warning("access_sso.jwks_unavailable", error=type(e).__name__)
            if _cache["keys"] is None:
                raise AccessTokenError("signing keys unavailable") from e
        return _cache["keys"]


# --- verification ---------------------------------------------------------------------------------------------

def verify_token(token: Optional[str]) -> dict:
    """Return the claims of a valid Access identity token, or raise AccessTokenError."""
    if not token or len(token) > 8192:
        raise AccessTokenError("missing token")
    issuer = f"https://{settings.ACCESS_TEAM_DOMAIN}"
    checks = {"iss": {"essential": True, "value": issuer}, "exp": {"essential": True}, "email": {"essential": True}}
    try:
        try:
            decoded = jwt.decode(token, _keyset(), algorithms=["RS256"])
        except JoseError:
            decoded = jwt.decode(token, _keyset(force=True), algorithms=["RS256"])  # key rotation: refresh once
        claims = decoded.claims
        aud = claims.get("aud")
        auds = [aud] if isinstance(aud, str) else list(aud or [])
        if not settings.ACCESS_AUD or settings.ACCESS_AUD not in auds:
            raise AccessTokenError("wrong audience")
        JWTClaimsRegistry(leeway=30, **checks).validate(claims)
    except AccessTokenError:
        raise
    except (JoseError, ValueError, KeyError, TypeError) as e:
        raise AccessTokenError(f"invalid token: {type(e).__name__}") from e
    email = claims.get("email")
    if not isinstance(email, str) or "@" not in email or len(email) > 255:
        raise AccessTokenError("no usable email")
    return claims


# --- account lookup / creation --------------------------------------------------------------------------------

_USERNAME_OK = re.compile(r"[^a-z0-9._-]")


def _new_username(db: Session, email: str) -> str:
    base = _USERNAME_OK.sub("", email.split("@")[0].lower())[:40] or "guest"
    if len(base) < 2:
        base = f"{base}x"
    name, n = base, 1
    while db.query(User.id).filter(func.lower(User.username) == name).first():
        n += 1
        name = f"{base}{n}"
    return name


def _create_guest(db: Session, request: Request, email: str, claims: dict) -> User:
    from backend.app.security_policy import service as policy

    local = email.split("@")[0]
    first = (str(claims.get("name") or "").split(" ")[0] or local)[:100]
    user = User(
        email=email,
        username=_new_username(db, email),
        first_name=first,
        last_name="(guest)",
        password=policy.generate(db),  # unknown to anyone; the visitor chooses their own at first visit
        is_admin=False,
    )
    user.password_changed_at = None  # "has not chosen a password yet": drives the first-visit steps
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Could not create the account. Try again.")
    record(db, AuditAction.USER_CREATED, request, None, user.id, "user",
           {"email": email, "username": user.username, "is_admin": False, "via": "access_sso"})
    return user


# --- routes ---------------------------------------------------------------------------------------------------

@router.get("/login/access/enabled")
def access_enabled():
    """Lets the sign-in page know whether to offer 'Continue with your invite'. Reveals nothing else."""
    return {"enabled": bool(settings.ACCESS_SSO_ENABLED and settings.ACCESS_TEAM_DOMAIN and settings.ACCESS_AUD)}


@router.post("/login/access")
async def login_with_access(request: Request, response: Response, db: Session = Depends(get_db)):
    if not (settings.ACCESS_SSO_ENABLED and settings.ACCESS_TEAM_DOMAIN and settings.ACCESS_AUD):
        raise HTTPException(status_code=404, detail="Not found")
    check_origin(request)
    ip = ratelimit.client_ip(request)
    ratelimit.check("login", ip, settings.RATE_LIMIT_LOGIN_FAILURES)
    denied = HTTPException(status_code=401, detail="Not signed in through the invitation")
    token = request.headers.get(HEADER)
    if not token:
        raise denied  # not counted: the page asks on every load
    try:
        claims = verify_token(token)
    except AccessTokenError as e:
        ratelimit.hit("login", ip, settings.RATE_LIMIT_LOGIN_WINDOW_SECONDS)
        logger.warning("access_sso.rejected", reason=str(e))
        raise denied

    email = claims["email"].strip().lower()
    user = db.query(User).filter(func.lower(User.email) == email).first()
    if user is None:
        if not settings.ACCESS_SSO_AUTO_CREATE:
            raise denied
        user = _create_guest(db, request, email, claims)

    stronger = (
        user.is_admin
        or user.is_super_admin
        or user.passkey_required
        or (user.mfa is not None and user.mfa.enabled)
        or user.is_locked_out()
    )
    if stronger or user.status != "active":
        db.rollback()
        logger.warning("access_sso.refused", user_id=user.id, status=user.status)
        raise HTTPException(status_code=403, detail="Sign in with your password.")

    out = await complete_login(db, request, response, user, method=METHOD)
    out["first_visit"] = user.password_changed_at is None
    return out


@router.post("/me/password/initial")
def set_initial_password(body: dict, request: Request, ctx=Depends(get_session_and_user), db: Session = Depends(get_db)):
    """First visit after an invitation sign-in: choose the password the account never had. Only for a session that
    was started through Access and an account whose password has never been chosen by its owner."""
    session, user, _ = ctx
    new_password = body.get("new_password") if isinstance(body, dict) else None
    if not isinstance(new_password, str) or not new_password:
        raise HTTPException(status_code=422, detail="Enter a new password")
    # Exactly the Access method: a password+TOTP session also lists "otp", and must not qualify.
    if user.password_changed_at is not None or list(session.amr or []) != amr_for(METHOD) or user.is_admin:
        raise HTTPException(status_code=403, detail="Not available")
    from backend.app.security_policy import service as policy

    policy.set_checked(db, user, new_password)
    revoke_user_sessions(db, user.id, except_id=session.id)
    record(db, AuditAction.USER_PASSWORD_CHANGED, request, user, user.id, "user", {"via": "first_visit"})
    db.commit()
    return {"success": True}
