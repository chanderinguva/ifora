"""Audit recording helper. Callers commit, so the audit row is atomic with the change."""

from typing import Any, Dict, Optional

from fastapi import Request
from sqlalchemy.orm import Session

from backend.app.audit.model import AuditAction, AuditEvent
from backend.app.users.model import User

_FORBIDDEN = {"password", "new_password", "current_password", "token", "secret"}


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
