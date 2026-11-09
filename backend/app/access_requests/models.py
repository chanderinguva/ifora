"""Self-service access requests (ADR 017)."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, text

from backend.app.db import Base
from backend.app.tenancy import TenantOwned


def _now():
    return datetime.now(timezone.utc)


class AppSelfService(TenantOwned, Base):
    """Per-application switch: may people who are not assigned ask for access? Absent row = no."""

    __tablename__ = "application_self_service"

    application_id = Column(Integer, ForeignKey("applications.id", ondelete="CASCADE"), primary_key=True)
    enabled = Column(Boolean, nullable=False, default=False)
    reason_required = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class AccessRequest(TenantOwned, Base):
    __tablename__ = "access_requests"
    __table_args__ = (Index("uq_access_request_pending", "user_id", "application_id", unique=True, postgresql_where=text("status = 'pending'")),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    application_id = Column(Integer, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    reason = Column(String(500), nullable=True)
    status = Column(String(10), nullable=False, default="pending", index=True)  # pending | approved | denied | canceled
    decided_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    decision_note = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
