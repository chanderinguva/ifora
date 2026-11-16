"""Human-readable device labels and opaque session handles for the self-service security pages (IFORA-43).

The label is a convenience for the person reading their own list ("Chrome on macOS"); it is derived from the User-Agent the
browser sent and is never used for a security decision. Session handles are keyed HMACs of (user, session): stable, opaque,
and useless to anyone else. The database id of a session is never shown.
"""

import hashlib
import hmac
from typing import Optional

from backend.app.config import settings

_BROWSERS = (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"), ("Chrome/", "Chrome"), ("CriOS/", "Chrome"), ("Safari/", "Safari"))
_SYSTEMS = (("iPhone", "iOS"), ("iPad", "iPadOS"), ("Android", "Android"), ("Windows", "Windows"), ("Mac OS X", "macOS"), ("Macintosh", "macOS"), ("CrOS", "ChromeOS"), ("Linux", "Linux"))


def label(user_agent: Optional[str]) -> str:
    ua = (user_agent or "")[:500]
    if not ua:
        return "Unknown device"
    browser = next((name for token, name in _BROWSERS if token in ua), None)
    system = next((name for token, name in _SYSTEMS if token in ua), None)
    if browser and system:
        return f"{browser} on {system}"
    return browser or system or "Unknown device"


def fingerprint(user_agent: Optional[str]) -> str:
    """Short stable id of a device class, used only to notice a sign-in from one this person has not used before."""
    return hashlib.sha256((user_agent or "").encode()).hexdigest()[:16]


def handle(user_id: int, session_id: int) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), f"session-handle:{user_id}:{session_id}".encode(), hashlib.sha256).hexdigest()[:32]


def matches(candidate: str, user_id: int, session_id: int) -> bool:
    return hmac.compare_digest(candidate or "", handle(user_id, session_id))


_KNOWN_DEVICE_MAX = 20
_KNOWN_DEVICE_DAYS = 90


def seen_before(user_id: int, user_agent: str | None) -> bool | None:
    """Record this device for the person and say whether it was already known.

    Returns None when there is no history yet (a first sign-in is not "new"), or when Redis is unavailable; best effort,
    it must never block a sign-in.
    """
    try:
        from backend.app import ratelimit

        r, key = ratelimit._redis(), f"kdev:{user_id}"
        fp = fingerprint(user_agent)
        had_history = r.scard(key) > 0
        known = bool(r.sismember(key, fp))
        if not known and r.scard(key) < _KNOWN_DEVICE_MAX:
            r.sadd(key, fp)
        r.expire(key, _KNOWN_DEVICE_DAYS * 86400)
        return known if had_history else None
    except Exception:  # noqa: BLE001
        return None
