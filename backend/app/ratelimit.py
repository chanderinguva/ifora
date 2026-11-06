"""Fixed-window rate limiting backed by Redis.

Used to throttle credential guessing per client IP. Per-account lockout (in the login route)
covers a known account; this covers spraying across many/unknown accounts.

Fails open if Redis is unavailable (logged), so a Redis outage cannot lock everyone out.
"""

import redis
import structlog
from fastapi import HTTPException, Request

from backend.app.config import settings

logger = structlog.get_logger(__name__)
_client = None


def _redis():
    global _client
    if _client is None:
        _client = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=1, socket_timeout=1)
    return _client


def client_ip(request: Request) -> str:
    # request.client is the direct peer. Behind a reverse proxy configure the proxy-headers
    # handling at the ASGI server (uvicorn --proxy-headers --forwarded-allow-ips) rather than
    # trusting X-Forwarded-For here, which any client could forge.
    return request.client.host if request.client else "unknown"


def _key(scope: str, ident: str) -> str:
    return f"rl:{scope}:{ident}"


def check(scope: str, ident: str, limit: int) -> None:
    """Raise 429 if `ident` already used up `limit` hits in the current window."""
    try:
        used = _redis().get(_key(scope, ident))
        if used is not None and int(used) >= limit:
            ttl = _redis().ttl(_key(scope, ident))
            raise HTTPException(
                status_code=429,
                detail="Too many attempts. Try again later.",
                headers={"Retry-After": str(max(ttl, 1))},
            )
    except redis.RedisError as e:
        logger.warning("ratelimit.redis_unavailable", error=str(e))


def hit(scope: str, ident: str, window_seconds: int) -> None:
    """Count one event; the window starts at the first hit."""
    try:
        r = _redis()
        key = _key(scope, ident)
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.expire(key, window_seconds, nx=True)
        pipe.execute()
    except redis.RedisError as e:
        logger.warning("ratelimit.redis_unavailable", error=str(e))


def reset(scope: str, ident: str) -> None:
    try:
        _redis().delete(_key(scope, ident))
    except redis.RedisError:
        pass
