"""User model for identity management."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from passlib.hash import argon2
import uuid
from sqlalchemy import Column, DateTime, Integer, String, Boolean, Text, UniqueConstraint
from sqlalchemy.orm import relationship, validates

from backend.app.db import Base
from backend.app.tenancy import TenantOwned


class UserStatus(str, Enum):
    """Account lifecycle, the same states Okta uses (lower-case). Only ACTIVE can sign in."""

    STAGED = "staged"                    # created, not yet activated
    PROVISIONED = "provisioned"          # activated, waiting for the user to finish setup (set a password)
    ACTIVE = "active"
    RECOVERY = "recovery"                # password reset requested
    PASSWORD_EXPIRED = "password_expired"
    LOCKED_OUT = "locked_out"
    SUSPENDED = "suspended"              # temporarily blocked; keeps groups and assignments
    DEPROVISIONED = "deprovisioned"      # deactivated; removed from every group


class User(TenantOwned, Base):
    """User account model."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
        UniqueConstraint("tenant_id", "username", name="uq_users_tenant_username"),
    )

    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Core identity
    # Opaque, stable, never-reused identifier exposed to relying parties as the OIDC `sub` (never the email or the row id).
    public_id = Column(String(36), nullable=False, unique=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(255), nullable=False, index=True)
    username = Column(String(100), nullable=False, index=True)

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

    # WebAuthn: stable random user handle (never PII) and the "passkey only" policy
    webauthn_handle = Column(String(64), nullable=True)
    passkey_required = Column(Boolean, default=False, nullable=False, server_default="false")
    lockout_until = Column(DateTime(timezone=True), nullable=True)
    password_changed_at = Column(DateTime(timezone=True), nullable=True)
    # One-time code an operator/super admin hands to an admin who must enrol a first factor.
    enrollment_code_hash = Column(String(64), nullable=True)
    enrollment_code_expires_at = Column(DateTime(timezone=True), nullable=True)

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

    @validates("username")
    def _username_is_immutable(self, _key: str, value: str) -> str:
        """The username is assigned once. (A database trigger enforces the same for raw SQL; migration 0050.)"""
        current = self.username   # loads the stored value if it was expired; None while the object is being built
        if current is not None and current != value:
            raise ValueError("A username cannot be changed once the account exists")
        return value

    def set_password(self, password: str) -> None:
        """Hash and set password using Argon2id."""
        self.password_hash = argon2.hash(password)
        from datetime import datetime, timezone

        self.password_changed_at = datetime.now(timezone.utc)

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
        return self.status == UserStatus.ACTIVE.value and not self.is_locked_out()

    def is_locked_out(self) -> bool:
        """Check if account is currently locked out."""
        if self.lockout_until is None:
            return False
        from datetime import datetime, timezone

        return datetime.now(timezone.utc) < self.lockout_until

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

    @property
    def has_second_factor(self) -> bool:
        """An enabled authenticator app, or any passkey (registered with user verification)."""
        return bool((self.mfa and self.mfa.enabled) or self.passkeys)

    @property
    def needs_mfa_setup(self) -> bool:
        """Admin policy: admins without a second factor may only manage their own account."""
        from backend.app.config import settings

        return bool(settings.ADMIN_MFA_REQUIRED and self.is_admin and not self.has_second_factor)

    @property
    def enrollment_code_by_email(self) -> bool:
        """True when this user may have their enrolment code mailed to them (never for super admins)."""
        from backend.app import mailer
        from backend.app.config import settings

        return bool(settings.ENROLLMENT_CODE_EMAIL and self.needs_mfa_setup and not self.is_super_admin and mailer.configured())

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
            "mfa_enabled": bool(self.mfa and self.mfa.enabled),
            "passkey_count": len(self.passkeys),
            "passkey_required": self.passkey_required,
            "mfa_setup_required": self.needs_mfa_setup,
            "enrollment_code_by_email": self.enrollment_code_by_email,
        }
        return result