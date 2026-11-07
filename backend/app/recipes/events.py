"""Transactional outbox emitters (ADR 008 D1).

Everything here only does ``db.add()`` on the caller's session: the event commits or rolls back together with the
change that caused it. Callers commit. Hooks are additive: `audit.service.record()` calls `emit_from_audit()`.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

import structlog
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.recipes.models import Recipe, RecipeOutbox

logger = structlog.get_logger(__name__)

EVENT_TYPES = (
    "user.created", "user.activated", "user.deactivated", "user.updated", "user.attribute_changed",
    "group.member_added", "group.member_removed", "login.failed",
    "user.deleted", "group.created", "group.deleted", "login.succeeded",
)
_AUDIT_TO_EVENT = {
    "USER_CREATED": "user.created",
    "USER_ACTIVATED": "user.activated",
    "USER_DEACTIVATED": "user.deactivated",
    "USER_UPDATED": "user.updated",
    "GROUP_MEMBER_ADDED": "group.member_added",
    "GROUP_MEMBER_REMOVED": "group.member_removed",
    "LOGIN_FAILURE": "login.failed",
    "USER_DELETED": "user.deleted",
    "GROUP_CREATED": "group.created",
    "GROUP_DELETED": "group.deleted",
    "LOGIN_SUCCESS": "login.succeeded",
}


def user_snapshot(user) -> Dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "status": user.status,
        "attributes": dict(user.get_profile_attributes() or {}),
    }


def has_listener(db: Session, event_type: str) -> bool:
    return (
        db.query(Recipe.id).filter(Recipe.enabled.is_(True), Recipe.published_trigger_type == event_type).first()
        is not None
    )


def emit(db: Session, event_type: str, data: Dict[str, Any], actor: Optional[Dict[str, Any]] = None) -> bool:
    """Stage one outbox row. Returns False when the feature is off or nobody listens."""
    if not settings.RECIPES_ENABLED:
        return False
    if not has_listener(db, event_type):
        return False
    origin = db.info.get("recipe_origin")
    if origin:
        actor = {"type": "recipe", "id": str(origin["recipe_id"])}
    now = datetime.now(timezone.utc)
    db.add(
        RecipeOutbox(
            event_type=event_type,
            payload={
                "type": event_type,
                "version": 1,
                "occurred_at": now.isoformat(),
                "actor": actor,
                "data": data,
            },
            depth=(origin["depth"] + 1) if origin else 0,
            origin_recipe_id=origin["recipe_id"] if origin else None,
            created_at=now,
        )
    )
    return True


def _actor_dict(actor) -> Optional[Dict[str, Any]]:
    return {"type": "user", "id": str(actor.id)} if actor is not None else None


def emit_from_audit(db: Session, action, actor, target_id, target_type, metadata: Optional[dict]) -> None:
    """Called by `audit.service.record()` for every audit row; maps the relevant ones to events."""
    event_type = _AUDIT_TO_EVENT.get(getattr(action, "value", str(action)))
    if event_type is None or not settings.RECIPES_ENABLED:
        return
    from backend.app.groups.model import Group
    from backend.app.users.model import User

    metadata = metadata or {}
    try:
        if event_type == "user.deleted" and target_id is not None:
            # the row is gone (or going) in this transaction: the snapshot is what the audit event knew
            data = {"user": {"id": int(target_id), "email": metadata.get("email", ""), "username": "", "first_name": "",
                             "last_name": "", "status": "deleted", "attributes": {}}}
        elif event_type in ("group.created", "group.deleted") and target_id is not None:
            data = {"group": {"id": int(target_id), "name": metadata.get("name", "")}}
        elif event_type == "login.succeeded" and target_id is not None:
            user = db.get(User, int(target_id))
            if user is None:
                return
            data = {"user": user_snapshot(user), "login": {"method": str(metadata.get("method", ""))}}
        elif event_type.startswith("user.") and target_id is not None:
            user = db.get(User, int(target_id))
            if user is None:
                return
            data = {"user": user_snapshot(user)}
        elif event_type.startswith("group.member_") and target_id is not None:
            group, user = db.get(Group, int(target_id)), db.get(User, int(metadata.get("user_id", 0)))
            if group is None or user is None:
                return
            data = {"group": {"id": group.id, "name": group.name}, "user": user_snapshot(user)}
        elif event_type == "login.failed":
            return  # emitted explicitly by the login route (needs the failure count)
        else:
            return
    except (TypeError, ValueError):
        return
    emit(db, event_type, data, _actor_dict(actor))


def emit_login_failed(db: Session, user, consecutive_failures: int) -> None:
    emit(db, "login.failed", {"user": user_snapshot(user), "login": {"consecutive_failures": consecutive_failures}})


def emit_attribute_changes(db: Session, user, old: Dict[str, Any], new: Dict[str, Any], actor=None) -> None:
    """One `user.attribute_changed` event per profile attribute whose value differs."""
    if not settings.RECIPES_ENABLED or not has_listener(db, "user.attribute_changed"):
        return
    snap = user_snapshot(user)
    for key in sorted(set(old) | set(new)):
        if old.get(key) != new.get(key):
            emit(
                db,
                "user.attribute_changed",
                {"user": snap, "attribute": {"key": key, "old": old.get(key), "new": new.get(key)}},
                _actor_dict(actor),
            )
