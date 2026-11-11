"""Keep a Cloudflare Access allowlist in step with the users (demo environments; off unless fully configured).

Inviting someone to the demo has two halves: an Ifora account, and permission to get past Cloudflare Access at all.
This adds the invited email to one Access policy's `include` list, and removes it again when the user is deleted.

Failures never block the Ifora operation: callers get a status string ("added", "already", "removed", "absent",
"disabled", "failed") to show to the administrator. The API token is meant to be limited to
"Access: Apps and Policies: Edit"; it is never logged.
"""

import threading
from typing import Callable, Optional

import httpx
import structlog

from backend.app.config import settings

logger = structlog.get_logger(__name__)

_BASE = "https://api.cloudflare.com/client/v4"
_lock = threading.Lock()  # read-modify-write of the policy: one at a time within this process
_KEEP = ("name", "decision", "include", "exclude", "require", "precedence", "session_duration",
         "purpose_justification_required", "purpose_justification_prompt", "approval_required", "approval_groups",
         "isolation_required")


def enabled() -> bool:
    return all((settings.ACCESS_ALLOWLIST_TOKEN, settings.ACCESS_ALLOWLIST_ACCOUNT_ID,
                settings.ACCESS_ALLOWLIST_APP_ID, settings.ACCESS_ALLOWLIST_POLICY_ID))


def _url() -> str:
    return (f"{_BASE}/accounts/{settings.ACCESS_ALLOWLIST_ACCOUNT_ID}/access/apps/"
            f"{settings.ACCESS_ALLOWLIST_APP_ID}/policies/{settings.ACCESS_ALLOWLIST_POLICY_ID}")


def _request(method: str, body: Optional[dict] = None) -> dict:
    """One Cloudflare API call; returns `result`. Replaced in tests."""
    r = httpx.request(method, _url(), json=body, timeout=8.0,
                      headers={"Authorization": f"Bearer {settings.ACCESS_ALLOWLIST_TOKEN}"})
    r.raise_for_status()
    data = r.json()
    if not data.get("success"):
        raise RuntimeError("Cloudflare API reported failure")
    return data["result"]


def _emails(include: list) -> list:
    return [(rule.get("email") or {}).get("email", "").lower() for rule in include]


def _write(policy: dict, include: list) -> None:
    body = {k: policy[k] for k in _KEEP if k in policy}
    body["include"] = include
    _request("PUT", body)


def _edit(change: Callable[[list], Optional[list]], done: str, noop: str) -> str:
    if not enabled():
        return "disabled"
    try:
        with _lock:
            policy = _request("GET")
            include = list(policy.get("include") or [])
            new = change(include)
            if new is None:
                return noop
            _write(policy, new)
            return done
    except Exception as e:  # noqa: BLE001 - never let the allowlist break creating or deleting a user
        logger.warning("access_allowlist.failed", error=type(e).__name__)
        return "failed"


def add(email: str) -> str:
    email = email.strip().lower()

    def change(include: list) -> Optional[list]:
        if email in _emails(include):
            return None
        return include + [{"email": {"email": email}}]

    return _edit(change, "added", "already")


def remove(email: str, keep: tuple = ()) -> str:
    """Remove an email from the allowlist unless it is in `keep` (addresses that must never lose access)."""
    email = email.strip().lower()
    if email in {k.lower() for k in keep}:
        return "kept"

    def change(include: list) -> Optional[list]:
        left = [r for r in include if (r.get("email") or {}).get("email", "").lower() != email]
        return None if len(left) == len(include) else left

    return _edit(change, "removed", "absent")
