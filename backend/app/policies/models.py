"""Network zones and per-application authentication policies (ADR 013)."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from backend.app.db import Base
from backend.app.tenancy import TenantOwned


def _now():
    return datetime.now(timezone.utc)


class NetworkZone(TenantOwned, Base):
    """A named set of IP ranges (CIDR) an authentication policy can allow or block."""

    __tablename__ = "network_zones"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_network_zones_tenant_name"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(80), nullable=False)
    cidrs = Column(JSONB, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class AppAuthPolicy(TenantOwned, Base):
    """What a sign-in to one application demands, beyond being assigned to it. No row = no extra demands."""

    __tablename__ = "app_auth_policies"
    __table_args__ = (CheckConstraint("reauth_minutes IS NULL OR reauth_minutes BETWEEN 5 AND 1440", name="ck_app_policy_reauth"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    application_id = Column(Integer, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, unique=True)
    require_mfa = Column(Boolean, nullable=False, default=False, server_default="false")
    reauth_minutes = Column(Integer, nullable=True)  # the sign-in must be younger than this
    allowed_zone_ids = Column(JSONB, nullable=False, default=list)  # non-empty: only these networks
    blocked_zone_ids = Column(JSONB, nullable=False, default=list)  # these networks never
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now)
