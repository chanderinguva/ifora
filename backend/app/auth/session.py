"""Session model for authentication."""

import secrets
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, Optional

from sqlalchemy import Column, DateTime, Integer, String, Boolean, ForeignKey
from sqlalchemy.orm import relationship

from backend.app.db import Base


class SessionStatus(str, Enum):
    """Session status."""

    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    INVALID = "invalid"


class Session(Base):
    """User session model using cryptographically secure opaque tokens."""

    __tablename__ = "sessions"

    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)

    # User relationship
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # Cryptographically secure opaque token (256 bits)
    token = Column(String(64), unique=True, nullable=False, index=True)

    # Status tracking
    status = Column(String(50), default=SessionStatus.ACTIVE.value, nullable=False)

    # Activity tracking
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    last_activity_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)

    # Context
    ip_address = Column(String(45), nullable=True)  # IPv6 compatible
    user_agent = Column(String(500), nullable=True)
    is_admin_session = Column(Boolean, default=False, nullable=False)

    def __init__(
        self,
        user_id: int,
        session_lifetime_hours: int = 8,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        is_admin_session: bool = False,
    ):
        self.user_id = user_id
        self.token = self._generate_token()
        self.is_admin_session = is_admin_session
        self.ip_address = ip_address
        self.user_agent = user_agent
        self.expires_at = datetime.utcnow() + timedelta(hours=session_lifetime_hours)

    @staticmethod
    def _generate_token() -> str:
        """Generate a cryptographically secure opaque token.

        Uses secrets.token_urlsafe for:
        - 256 bits of entropy
        - Cryptographically secure random generation
        - URL-safe encoding
        """
        return secrets.token_urlsafe(32)

    @property
    def is_expired(self) -> bool:
        """Check if session has expired."""
        return datetime.utcnow() > self.expires_at or self.status != SessionStatus.ACTIVE.value

    def revoke(self) -> None:
        """Revoke the session."""
        self.status = SessionStatus.REVOKED.value

    def extend(self, additional_hours: int = 8) -> None:
        """Extend session lifetime."""
        self.expires_at = datetime.utcnow() + timedelta(hours=additional_hours)
        self.last_activity_at = datetime.utcnow()

    def touch(self) -> None:
        """Update last activity timestamp."""
        self.last_activity_at = datetime.utcnow()

    @classmethod
    def create(cls, **kwargs) -> "Session":
        """Factory method to create a new session."""
        session = cls(**kwargs)
        return session

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_activity_at": self.last_activity_at.isoformat() if self.last_activity_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "is_expired": self.is_expired,
            "is_admin_session": self.is_admin_session,
        }