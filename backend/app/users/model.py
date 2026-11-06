"""User model for identity management."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from passlib.hash import argon2
from sqlalchemy import Column, DateTime, Integer, String, Boolean, Text
from sqlalchemy.orm import relationship

from backend.app.db import Base


class UserStatus(str, Enum):
    """User account status."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING_ACTIVATION = "pending_activation"
    LOCKED_OUT = "locked_out"


class User(Base):
    """User account model."""

    __tablename__ = "users"

    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Core identity
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)

    # Password hash (Argon2id)
    password_hash = Column(String(255), nullable=False)

    # Personal info
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)

    # Profile extensible attributes (JSON)
    profile_attributes = Column(Text, nullable=True)

    # Status and lifecycle
    status = Column(String(50), default=UserStatus.ACTIVE.value, nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    is_super_admin = Column(Boolean, default=False, nullable=False)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    locked_out_at = Column(DateTime(timezone=True), nullable=True)

    # Login throttling
    failed_login_attempts = Column(Integer, default=0, nullable=False)
    lockout_until = Column(DateTime(timezone=True), nullable=True)

    def __init__(
        self,
        email: str,
        username: str,
        first_name: str,
        last_name: str,
        password: str,
        profile_attributes: Optional[Dict[str, Any]] = None,
        is_admin: bool = False,
        is_super_admin: bool = False,
    ):
        self.email = email.lower()
        self.username = username
        self.first_name = first_name
        self.last_name = last_name
        self.set_password(password)
        self.profile_attributes = profile_attributes
        self.is_admin = is_admin
        self.is_super_admin = is_super_admin

    def set_password(self, password: str) -> None:
        """Hash and set password using Argon2id."""
        self.password_hash = argon2.hash(password)

    def verify_password(self, password: str) -> bool:
        """Verify password against stored hash.

        Uses Argon2id which provides:
        - Memory-hard computation
        - Resistance to GPU/ASIC attacks
        - Timing-attack resistance
        """
        try:
            return argon2.verify(password, self.password_hash)
        except Exception:
            return False

    @property
    def is_active(self) -> bool:
        """Check if user is active."""
        return self.status == UserStatus.ACTIVE.value and not self.is_locked_out

    def is_locked_out(self) -> bool:
        """Check if account is currently locked out."""
        if self.lockout_until is None:
            return False
        if self.failed_login_attempts >= 5:
            from datetime import datetime

            return datetime.utcnow() < self.lockout_until
        return False

    @property
    def name(self) -> str:
        """Return full name."""
        return f"{self.first_name} {self.last_name}"

    def get_profile_attributes(self) -> Dict[str, Any]:
        """Get profile attributes as dictionary."""
        if self.profile_attributes:
            try:
                import json

                return json.loads(self.profile_attributes)
            except (json.JSONDecodeError, TypeError):
                return {}
        return {}

    def set_profile_attributes(self, attributes: Dict[str, Any]) -> None:
        """Set profile attributes from dictionary."""
        import json

        self.profile_attributes = json.dumps(attributes)

    def to_dict(self, include_sensitive: bool = False) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = {
            "id": self.id,
            "email": self.email,
            "username": self.username,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "status": self.status,
            "is_admin": self.is_admin,
            "is_super_admin": self.is_super_admin,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
            "profile_attributes": self.get_profile_attributes(),
        }
        return result