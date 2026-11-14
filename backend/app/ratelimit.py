"""Fixed-window rate limiting backed by Redis.

Used to throttle credential guessing per client IP. Per-account lockout (in the login route)
covers a known account; this covers spraying across many/unknown accounts.

When Redis is unavailable, `check`/`consume` on a credential scope (FAIL_CLOSED_SCOPES) answer 503 instead of
letting the request through, so an outage (or someone knocking Redis over) cannot switch off brute-force
protection. Other scopes (upload and request-volume limits) still fail open: those are not guessing defences.
Rollback: RATE_LIMIT_FAIL_CLOSED=false restores fail-open everywhere. Already-valid sessions never touch these
scopes, so an outage does not log anyone out.
"""

import threading
import time
from typing import Dict

import redis
import structlog
from fastapi import HTTPException, Request

from backend.app.config import settings

logger = structlog.get_logger(__name__)
_client = None

FAIL_CLOSED_SCOPES = frozenset(
    {
        "login",
        "login_locked",
        "mfa_fail_user",
        "mfa_fail_ip",
        "bootstrap",
        "pwreset_ip",
        "pwreset_email",
        "pwreset_email_ip",
        "pwtoken_ip",
        "oauth_token",
        "api_token_fail",
        "scim_auth_fail",
    }
)

_stats_lock = threading.Lock()
_stats: Dict[str, float] = {"redis_errors": 0, "last_error_at": 0.0}


def _redis():
    global _client
    if _client is None:
        _client = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=1, socket_timeout=1)
    return _client


def stats() -> Dict[str, float]:
    """Counters for /metrics: Redis errors seen by this process."""
    with _stats_lock:
        return dict(_stats)


def _redis_failed(scope: str, error: Exception) -> None:
    with _stats_lock:
        _stats["redis_errors"] += 1
        _stats["last_error_at"] = time.time()
    fail_closed = settings.RATE_LIMIT_FAIL_CLOSED and scope in FAIL_CLOSED_SCOPES
    logger.warning("ratelimit.redis_unavailable", scope=scope, fail_closed=fail_closed, error=type(error).__name__)
    if fail_closed:
        raise HTTPException(
            status_code=503,
            detail="Service temporarily unavailable. Try again shortly.",
            headers={"Retry-After": "5"},
        )


def _too_many(ttl: int) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail="Too many attempts. Try again later.",
        headers={"Retry-After": str(max(ttl, 1))},
    )


def client_ip(request: Request) -> str:
    # request.client is the direct peer. Behind a reverse proxy configure the proxy-headers
    # handling at the ASGI server (uvicorn --proxy-headers --forwarded-allow-ips) rather than
    # trusting X-Forwarded-For here, which any client could forge.
    return request.client.host if request.client else "unknown"


def _key(scope: str, ident: str) -> str:
    return f"rl:{scope}:{ident}"


def is_limited(scope: str, ident: str, limit: int) -> bool:
    """True if `ident` already used up `limit` hits in the current window. Fails closed on credential scopes."""
    try:
        used = _redis().get(_key(scope, ident))
        return used is not None and int(used) >= limit
    except redis.RedisError as e:
        _redis_failed(scope, e)
        return False


def check(scope: str, ident: str, limit: int) -> None:
    """Raise 429 if `ident` already used up `limit` hits in the current window."""
    if is_limited(scope, ident, limit):
        try:
            ttl = _redis().ttl(_key(scope, ident))
        except redis.RedisError:
            ttl = 1
        raise _too_many(ttl)


def hit(scope: str, ident: str, window_seconds: int) -> None:
    """Count one event; the window starts at the first hit. Best effort: `check` already guards the request."""
    try:
        _incr(scope, ident, window_seconds)
    except redis.RedisError as e:
        with _stats_lock:
            _stats["redis_errors"] += 1
            _stats["last_error_at"] = time.time()
        logger.warning("ratelimit.redis_unavailable", scope=scope, fail_closed=False, error=type(e).__name__)


def _incr(scope: str, ident: str, window_seconds: int) -> int:
    key = _key(scope, ident)
    pipe = _redis().pipeline()  # MULTI/EXEC: the counter and its expiry are set together
    pipe.incr(key)
    pipe.expire(key, window_seconds, nx=True)
    pipe.ttl(key)
    count, _, _ttl = pipe.execute()
    return int(count)


def consume(scope: str, ident: str, limit: int, window_seconds: int) -> None:
    """Atomically count one event and raise 429 once more than `limit` have happened in the window.

    The decision comes from the INCR result, so two concurrent callers at limit-1 cannot both be admitted (unlike
    check() followed by hit()). Use it where every call counts, not only failures.
    """
    try:
        key = _key(scope, ident)
        pipe = _redis().pipeline()
        pipe.incr(key)
        pipe.expire(key, window_seconds, nx=True)
        pipe.ttl(key)
        count, _, ttl = pipe.execute()
    except redis.RedisError as e:
        _redis_failed(scope, e)
        return
    if int(count) > limit:
        raise _too_many(int(ttl))


def reset(scope: str, ident: str) -> None:
    try:
        _redis().delete(_key(scope, ident))
    except redis.RedisError:
        pass
