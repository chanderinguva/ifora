"""MFA persistence: enrolled TOTP secret, recovery codes, and login challenges."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import backref, relationship

from backend.app.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class UserMFA(Base):
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


class MFARecoveryCode(Base):
    __tablename__ = "mfa_recovery_codes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    code_hash = Column(String(64), nullable=False, index=True)  # SHA-256 of the normalised code
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class MFAChallenge(Base):
    """Short-lived proof that the password step succeeded; exchanged for a session after MFA."""

    __tablename__ = "mfa_challenges"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True)
    attempts = Column(Integer, nullable=False, default=0)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
