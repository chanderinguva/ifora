"""Administrator role assignments (ADR 014). A user with no rows is a full organization administrator (the pre-roles behaviour)."""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint

from backend.app.db import Base
from backend.app.tenancy import TenantOwned


class AdminRoleAssignment(TenantOwned, Base):
    __tablename__ = "admin_role_assignments"
    __table_args__ = (UniqueConstraint("user_id", "role", name="uq_admin_role_user_role"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(32), nullable=False)
    granted_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
