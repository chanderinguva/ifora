"""MFA persistence: enrolled TOTP secret, recovery codes, and login challenges."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import backref, relationship

from backend.app.db import Base
from backend.app.tenancy import TenantOwned


def _now() -> datetime:
    return datetime.now(timezone.utc)


class UserMFA(TenantOwned, Base):
    """One TOTP enrolment per user. `enabled` stays False until the first code is confirmed."""

    __tablename__ = "user_mfa"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    secret_encrypted = Column(String(255), nullable=False)  # Fernet token; never stored in clear
    enabled = Column(Boolean, nullable=False, default=False)
    # Highest TOTP time-step already accepted; a code for a step <= this is a replay.
    last_used_step = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    enabled_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", backref=backref("mfa", uselist=False, cascade="all, delete-orphan"))


class UserEmailOTP(TenantOwned, Base):
    """Email one-time code as a second factor (IFORA-60). Always sent to the account's own address, never one a user types in.

    Only a keyed hash of the current code is stored. `enabled` stays False until the first code is confirmed. After
    EMAIL_OTP_MAX_ATTEMPTS wrong tries the code is destroyed and `locked_until` blocks a new one for a cooldown."""

    __tablename__ = "user_email_otp"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    enabled = Column(Boolean, nullable=False, default=False)
    enabled_at = Column(DateTime(timezone=True), nullable=True)
    code_hash = Column(String(64), nullable=True)
    code_expires_at = Column(DateTime(timezone=True), nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime(timezone=True), nullable=True)
    last_sent_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    user = relationship("User", backref=backref("email_otp", uselist=False, cascade="all, delete-orphan"))


class MFARecoveryCode(TenantOwned, Base):
    __tablename__ = "mfa_recovery_codes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    code_hash = Column(String(64), nullable=False, index=True)  # SHA-256 of the normalised code
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class MFAChallenge(TenantOwned, Base):
    """Short-lived proof that the password step succeeded; exchanged for a session after MFA."""

    __tablename__ = "mfa_challenges"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True)
    attempts = Column(Integer, nullable=False, default=0)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
