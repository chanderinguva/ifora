"""Organization-wide password, lockout and session policy (ADR 018)."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint

from backend.app.db import Base
from backend.app.tenancy import TenantOwned


def _now():
    return datetime.now(timezone.utc)


class OrgSecurityPolicy(TenantOwned, Base):
    """At most one row per tenant. No row means the built-in defaults (the behaviour before this feature)."""

    __tablename__ = "org_security_policy"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_org_security_policy_tenant"),
        CheckConstraint("email_otp_members IN ('off','allowed')", name="ck_org_policy_email_otp_members"),
        CheckConstraint("email_otp_admins IN ('off','allowed','required')", name="ck_org_policy_email_otp_admins"),
        CheckConstraint("push_members IN ('off','allowed')", name="ck_org_policy_push_members"),
        CheckConstraint("push_admins IN ('off','allowed','required')", name="ck_org_policy_push_admins"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    min_length = Column(Integer, nullable=False)
    require_mixed_case = Column(Boolean, nullable=False)
    require_digit = Column(Boolean, nullable=False)
    require_symbol = Column(Boolean, nullable=False)
    no_user_info = Column(Boolean, nullable=False)
    history_count = Column(Integer, nullable=False)
    max_age_days = Column(Integer, nullable=False)
    max_failed_attempts = Column(Integer, nullable=False)
    lockout_minutes = Column(Integer, nullable=False)
    session_lifetime_hours = Column(Integer, nullable=False)
    idle_timeout_minutes = Column(Integer, nullable=False)
    # Email one-time code factor (IFORA-60), per audience: off | allowed | required (required applies to administrators only)
    email_otp_members = Column(String(10), nullable=False, default="off", server_default="off")
    email_otp_admins = Column(String(10), nullable=False, default="off", server_default="off")
    push_members = Column(String(10), nullable=False, default="off", server_default="off")
    push_admins = Column(String(10), nullable=False, default="off", server_default="off")
    updated_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class PasswordHistory(TenantOwned, Base):
    """Argon2id hashes of a user's earlier passwords, only so reuse can be refused."""

    __tablename__ = "password_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
