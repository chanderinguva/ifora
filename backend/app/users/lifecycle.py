"""User lifecycle (Okta-style statuses) and its side effects, in one place so every entry point behaves the same.

    staged -> provisioned -> active <-> suspended
                              active -> recovery | password_expired | locked_out -> active
    any -> deprovisioned (deactivate) -> staged/provisioned/active (reactivate)

Only `active` can sign in. Leaving `active` ends every session. Entering `deprovisioned` removes the user from every
group, manual and rule-based (the default offboarding rule); reactivating does not restore manual memberships, which
is what Okta does too. Rules re-add what they grant.
"""

from typing import Optional

from sqlalchemy.orm import Session

from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.auth.sessions_util import revoke_user_sessions
from backend.app.groups import rules as group_rules
from backend.app.users.model import User, UserStatus

STATUSES = tuple(s.value for s in UserStatus)
ACTIVE = UserStatus.ACTIVE.value
DEPROVISIONED = UserStatus.DEPROVISIONED.value
STATUS_PATTERN = "^(" + "|".join(STATUSES) + ")$"
LEGACY = {"inactive": DEPROVISIONED, "pending_activation": UserStatus.PROVISIONED.value}


def normalize(value: str) -> str:
    return LEGACY.get(value, value)


def set_status(db: Session, user: User, new: str, request=None, actor: Optional[User] = None, *, audit: bool = True) -> dict:
    """Move a user to `new`. Returns what happened; the caller commits. A no-op when the status is unchanged."""
    new = normalize(new)
    if new not in STATUSES:
        raise ValueError(f"unknown status '{new}'")
    old = user.status
    if old == new:
        return {"changed": False, "old": old, "new": new, "groups_removed": 0, "sessions_revoked": 0}
    user.status = new
    result = {"changed": True, "old": old, "new": new, "groups_removed": 0, "sessions_revoked": 0}
    if new == ACTIVE:
        user.failed_login_attempts = 0
        user.lockout_until = None
    else:
        result["sessions_revoked"] = revoke_user_sessions(db, user.id)
    db.flush()
    if new == DEPROVISIONED:
        result["groups_removed"] = group_rules.remove_all_memberships(db, user, request, actor)
    group_rules.evaluate_user(db, user, request, actor)
    if audit:
        action = AuditAction.USER_DEACTIVATED if new == DEPROVISIONED else (
            AuditAction.USER_ACTIVATED if new == ACTIVE and old in (DEPROVISIONED, "staged", "provisioned") else AuditAction.USER_STATUS_CHANGED)
        record(db, action, request, actor, user.id, "user",
               {"changed": {"status": new}, "from": old, "groups_removed": result["groups_removed"]})
    return result
