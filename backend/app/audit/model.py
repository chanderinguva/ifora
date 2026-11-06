"""Audit event model for tracking system activities."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from sqlalchemy import Column, DateTime, Enum as SAEnum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from backend.app.db import Base
from backend.app.tenancy import TenantOwned


class AuditAction(str, Enum):
    """Types of audit actions."""

    USER_CREATED = "USER_CREATED"
    USER_UPDATED = "USER_UPDATED"
    USER_DEACTIVATED = "USER_DEACTIVATED"
    USER_ACTIVATED = "USER_ACTIVATED"
    USER_PASSWORD_CHANGED = "USER_PASSWORD_CHANGED"
    USER_DELETED = "USER_DELETED"
    PROFILE_UPDATED = "PROFILE_UPDATED"
    GROUP_CREATED = "GROUP_CREATED"
    GROUP_UPDATED = "GROUP_UPDATED"
    GROUP_DELETED = "GROUP_DELETED"
    GROUP_MEMBER_ADDED = "GROUP_MEMBER_ADDED"
    GROUP_MEMBER_REMOVED = "GROUP_MEMBER_REMOVED"
    SESSION_CREATED = "SESSION_CREATED"
    SESSION_INVALIDATED = "SESSION_INVALIDATED"
    LOGIN_SUCCESS = "LOGIN_SUCCESS"
    LOGIN_FAILURE = "LOGIN_FAILURE"
    LOGOUT = "LOGOUT"
    ADMIN_BOOTSTRAP = "ADMIN_BOOTSTRAP"
    MFA_ENABLED = "MFA_ENABLED"
    MFA_DISABLED = "MFA_DISABLED"
    MFA_RESET = "MFA_RESET"
    ENROLLMENT_CODE_ISSUED = "ENROLLMENT_CODE_ISSUED"
    ROLE_SWITCHED = "ROLE_SWITCHED"
    MFA_RECOVERY_USED = "MFA_RECOVERY_USED"
    MFA_RECOVERY_REGENERATED = "MFA_RECOVERY_REGENERATED"
    MFA_CHALLENGE_FAILED = "MFA_CHALLENGE_FAILED"
    PASSKEY_REGISTERED = "PASSKEY_REGISTERED"
    PASSKEY_REMOVED = "PASSKEY_REMOVED"
    PASSKEY_RENAMED = "PASSKEY_RENAMED"
    PASSKEY_LOGIN_FAILED = "PASSKEY_LOGIN_FAILED"
    PASSKEY_POLICY_CHANGED = "PASSKEY_POLICY_CHANGED"
    PASSKEY_COUNTER_ANOMALY = "PASSKEY_COUNTER_ANOMALY"
    OIDC_KEY_CREATED = "OIDC_KEY_CREATED"
    PROFILE_ATTRIBUTE_CREATED = "PROFILE_ATTRIBUTE_CREATED"
    PROFILE_ATTRIBUTE_UPDATED = "PROFILE_ATTRIBUTE_UPDATED"
    PROFILE_ATTRIBUTE_DELETED = "PROFILE_ATTRIBUTE_DELETED"
    OIDC_CLIENT_CREATED = "OIDC_CLIENT_CREATED"
    OIDC_CLIENT_UPDATED = "OIDC_CLIENT_UPDATED"
    OIDC_CLIENT_DELETED = "OIDC_CLIENT_DELETED"
    OIDC_CLIENT_SECRET_ROTATED = "OIDC_CLIENT_SECRET_ROTATED"
    OIDC_CLIENT_SECRET_REVOKED = "OIDC_CLIENT_SECRET_REVOKED"
    GROUP_RULE_CREATED = "GROUP_RULE_CREATED"
    GROUP_RULE_UPDATED = "GROUP_RULE_UPDATED"
    GROUP_RULE_ACTIVATED = "GROUP_RULE_ACTIVATED"
    GROUP_RULE_DEACTIVATED = "GROUP_RULE_DEACTIVATED"
    GROUP_RULE_DELETED = "GROUP_RULE_DELETED"
    OIDC_KEY_ROTATED = "OIDC_KEY_ROTATED"


class AuditEventType(str, Enum):
    """High-level audit event categories."""

    AUTHENTICATION = "AUTHENTICATION"
    AUTHORIZATION = "AUTHORIZATION"
    USER_MANAGEMENT = "USER_MANAGEMENT"
    GROUP_MANAGEMENT = "GROUP_MANAGEMENT"
    SYSTEM = "SYSTEM"


class AuditEvent(TenantOwned, Base):
    """Audit event record for tracking sensitive operations."""

    __tablename__ = "audit_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False, index=True)

    # Actor information (never include raw credentials)
    actor_id = Column(String(255), nullable=True)
    actor_type = Column(String(50), nullable=True)
    actor_ip_address = Column(String(45), nullable=True)  # IPv6 compatible

    # Action details
    action = Column(String(50), nullable=False, index=True)
    event_type = Column(String(50), nullable=False)

    # Target (user, group, etc.)
    target_id = Column(String(255), nullable=True)
    target_type = Column(String(50), nullable=True)

    # Metadata - sanitized, no secrets. Named event_metadata because
    # 'metadata' is reserved by SQLAlchemy's Declarative API.
    event_metadata = Column("metadata", JSONB, nullable=True)

    # Additional details as text
    details = Column(Text, nullable=True)

    def __init__(
        self,
        action: AuditAction,
        actor_id: Optional[str] = None,
        actor_type: Optional[str] = None,
        actor_ip_address: Optional[str] = None,
        target_id: Optional[str] = None,
        target_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        details: Optional[str] = None,
    ):
        self.action = action.value
        self.event_type = self._get_event_type(action)
        self.actor_id = actor_id
        self.actor_type = actor_type
        self.actor_ip_address = actor_ip_address
        self.target_id = target_id
        self.target_type = target_type
        self.event_metadata = metadata
        self.details = details

    @staticmethod
    def _get_event_type(action: AuditAction) -> str:
        """Map audit action to event type."""
        auth_actions = {
            AuditAction.LOGIN_SUCCESS,
            AuditAction.LOGIN_FAILURE,
            AuditAction.LOGOUT,
            AuditAction.SESSION_CREATED,
            AuditAction.SESSION_INVALIDATED,
            AuditAction.MFA_ENABLED,
            AuditAction.MFA_DISABLED,
            AuditAction.MFA_RESET,
            AuditAction.MFA_RECOVERY_USED,
            AuditAction.MFA_RECOVERY_REGENERATED,
            AuditAction.MFA_CHALLENGE_FAILED,
            AuditAction.PASSKEY_REGISTERED,
            AuditAction.PASSKEY_REMOVED,
            AuditAction.PASSKEY_RENAMED,
            AuditAction.PASSKEY_LOGIN_FAILED,
            AuditAction.PASSKEY_POLICY_CHANGED,
            AuditAction.PASSKEY_COUNTER_ANOMALY,
            AuditAction.ROLE_SWITCHED,
        }
        user_actions = {
            AuditAction.USER_CREATED,
            AuditAction.USER_UPDATED,
            AuditAction.USER_DEACTIVATED,
            AuditAction.USER_ACTIVATED,
            AuditAction.USER_PASSWORD_CHANGED,
            AuditAction.USER_DELETED,
            AuditAction.PROFILE_UPDATED,
            AuditAction.PROFILE_ATTRIBUTE_CREATED,
            AuditAction.PROFILE_ATTRIBUTE_UPDATED,
            AuditAction.PROFILE_ATTRIBUTE_DELETED,
        }
        group_actions = {
            AuditAction.GROUP_CREATED,
            AuditAction.GROUP_UPDATED,
            AuditAction.GROUP_DELETED,
            AuditAction.GROUP_MEMBER_ADDED,
            AuditAction.GROUP_MEMBER_REMOVED,
            AuditAction.GROUP_RULE_CREATED,
            AuditAction.GROUP_RULE_UPDATED,
            AuditAction.GROUP_RULE_ACTIVATED,
            AuditAction.GROUP_RULE_DEACTIVATED,
            AuditAction.GROUP_RULE_DELETED,
        }

        if action in auth_actions:
            return AuditEventType.AUTHENTICATION.value
        elif action in user_actions:
            return AuditEventType.USER_MANAGEMENT.value
        elif action in group_actions:
            return AuditEventType.GROUP_MANAGEMENT.value
        else:
            return AuditEventType.SYSTEM.value

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "actor_id": self.actor_id,
            "actor_type": self.actor_type,
            "actor_ip_address": self.actor_ip_address,
            "action": self.action,
            "event_type": self.event_type,
            "target_id": self.target_id,
            "target_type": self.target_type,
            "metadata": self.event_metadata,
        }