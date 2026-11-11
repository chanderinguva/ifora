"""Startup guards: refuse to boot in production with an insecure configuration (IFORA-49 / SEC-A-5).

`validate_settings` is pure: it reads a settings object and an environment mapping and returns a list of problems.
Messages name the setting and never contain its value, so a refusal cannot leak a secret into logs.
Development (the default) is never restricted.
"""

import os
from typing import List, Mapping, Optional

_PLACEHOLDER_WORDS = ("changeme", "change-me", "change_me", "example", "placeholder", "password", "secret", "default", "test", "xxxx")
_MIN_SECRET_LEN = 32


def is_production(settings) -> bool:
    return str(settings.ENVIRONMENT).strip().lower() == "production"


def _weak_secret(value: str) -> bool:
    v = (value or "").strip()
    if len(v) < _MIN_SECRET_LEN or len(set(v)) < 10:
        return True
    low = v.lower()
    return any(w in low for w in _PLACEHOLDER_WORDS)


def validate_settings(settings, env: Optional[Mapping[str, str]] = None) -> List[str]:
    """Problems that must stop a production start. Empty list: fine (always empty outside production)."""
    if not is_production(settings):
        return []
    env = os.environ if env is None else env
    problems: List[str] = []

    if not settings.SESSION_COOKIE_SECURE:
        problems.append("ENVIRONMENT=production requires SESSION_COOKIE_SECURE=true (serve the API over HTTPS)")
    for name in ("SECRET_KEY", "ADMIN_SECRET_KEY"):
        if _weak_secret(getattr(settings, name, "")):
            problems.append(f"{name} is missing, too short (< {_MIN_SECRET_LEN}), low-entropy or a placeholder; generate a random value")
    if settings.SECRET_KEY and settings.SECRET_KEY == settings.ADMIN_SECRET_KEY:
        problems.append("SECRET_KEY and ADMIN_SECRET_KEY must be different values")
    if not settings.OIDC_KEY_ENCRYPTION_KEY:
        problems.append("OIDC_KEY_ENCRYPTION_KEY must be set in production (a Fernet key different from MFA_ENCRYPTION_KEY)")
    elif settings.OIDC_KEY_ENCRYPTION_KEY == settings.MFA_ENCRYPTION_KEY:
        problems.append("OIDC_KEY_ENCRYPTION_KEY must differ from MFA_ENCRYPTION_KEY")
    if any(o.strip() == "*" for o in settings.CORS_ORIGINS):
        problems.append("CORS_ORIGINS must not contain '*' in production")
    if settings.DEBUG:
        problems.append("DEBUG must be false in production")
    if getattr(settings, "ACCESS_SSO_ENABLED", False):
        team = getattr(settings, "ACCESS_TEAM_DOMAIN", "")
        if not team or "/" in team or not getattr(settings, "ACCESS_AUD", ""):
            problems.append("ACCESS_SSO_ENABLED requires ACCESS_TEAM_DOMAIN (a bare host name) and ACCESS_AUD")
    for name in ("PUBLIC_APP_URL", "OIDC_ISSUER"):
        if not str(getattr(settings, name, "")).lower().startswith("https://"):
            problems.append(f"{name} must be an https:// URL in production")
    return problems


def forwarded_ips_is_default(env: Optional[Mapping[str, str]] = None) -> bool:
    """True when uvicorn will only trust proxy headers from loopback (FORWARDED_ALLOW_IPS unset or 127.0.0.1)."""
    env = os.environ if env is None else env
    return env.get("FORWARDED_ALLOW_IPS", "127.0.0.1").strip() in ("", "127.0.0.1")
