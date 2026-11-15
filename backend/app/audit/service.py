"""Audit recording helper. Callers commit, so the audit row is atomic with the change."""

from typing import Any, Dict, Optional

from fastapi import Request
from sqlalchemy.orm import Session

from backend.app.audit.model import AuditAction, AuditEvent
from backend.app.users.model import User

_FORBIDDEN = {"password", "new_password", "current_password", "token", "secret"}


# Actions shown in a person's own activity list: keep which browser did it (IFORA-43).
DEVICE_ACTIONS = frozenset({
    "LOGIN_SUCCESS", "LOGIN_FAILURE", "LOGOUT", "USER_PASSWORD_CHANGED", "MFA_ENABLED", "MFA_DISABLED", "MFA_RESET",
    "MFA_RECOVERY_USED", "MFA_CHALLENGE_FAILED", "MFA_RECOVERY_REGENERATED", "PASSKEY_REGISTERED", "PASSKEY_REMOVED",
    "PASSKEY_LOGIN_FAILED", "PASSKEY_POLICY_CHANGED", "SESSION_REVOKED", "SESSIONS_REVOKED",
})


def device_of(request) -> str:
    return (request.headers.get("user-agent") or "")[:300]


def record(
    db: Session,
    action: AuditAction,
    request: Optional[Request] = None,
    actor: Optional[User] = None,
    target_id: Optional[int] = None,
    target_type: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Stage an audit event (no commit). Secrets in metadata are dropped."""
    safe = {k: v for k, v in (metadata or {}).items() if k.lower() not in _FORBIDDEN}
    if request is not None and getattr(action, "value", action) in DEVICE_ACTIONS:
        safe.setdefault("user_agent", device_of(request))
    method = getattr(getattr(request, "state", None), "stepup_method", None) if request is not None else None
    if method:  # a sensitive admin action carries how the admin proved themselves again (IFORA-33)
        safe["stepup"] = method
    db.add(
        AuditEvent(
            action=action,
            actor_id=str(actor.id) if actor else None,
            actor_type="user" if actor else None,
            actor_ip_address=request.client.host if request and request.client else None,
            target_id=str(target_id) if target_id is not None else None,
            target_type=target_type,
            metadata=safe or None,
        )
    )
    # Transactional outbox for the recipe engine (ADR 008): same session, so same commit/rollback as the change.
    from backend.app.recipes.events import emit_from_audit

    emit_from_audit(db, action, actor, target_id, target_type, safe)
    from backend.app.provisioning.service import on_audit

    on_audit(db, action, target_id, safe)  # outbound provisioning (ADR 009): queue tasks in the same transaction
