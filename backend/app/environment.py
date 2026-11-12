"""Environment identity shared by the UI and identity-notification emails.

Do not use NODE_ENV to infer deployment identity: the same compiled UI may serve any
environment. The backend ENVIRONMENT value is authoritative for this deployment.
"""
from backend.app.config import settings

_ALIASES = {
    "prod": "production", "production": "production",
    "dev": "development", "development": "development",
    "demo": "demo", "preview": "demo", "sandbox": "demo",
    "stage": "staging", "staging": "staging",
    "test": "test", "testing": "test",
}
_PREFIXES = {"demo": "DEMO", "development": "DEV", "staging": "STAGING", "test": "TEST"}


def name() -> str:
    raw = (settings.ENVIRONMENT or "").strip().lower()
    # Unknown environments must not silently appear to be production.
    return _ALIASES.get(raw, "development")


def label() -> str:
    return "PRODUCTION" if name() == "production" else _PREFIXES[name()]


def subject(value: str) -> str:
    """Non-production identity email subjects are unmistakable in the inbox."""
    prefix = "" if name() == "production" else f"[{label()}] "
    return prefix + value
