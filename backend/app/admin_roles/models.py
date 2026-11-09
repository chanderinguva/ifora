"""Administrator role assignments (ADR 014, 019). Roles come from direct rows and from the user's groups; no role means no administrator access."""

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


class GroupAdminRole(TenantOwned, Base):
    """An administrator role granted to every member of a group (ADR 019). Only team groups may carry roles."""

    __tablename__ = "group_admin_roles"
    __table_args__ = (UniqueConstraint("group_id", "role", name="uq_group_admin_role"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(32), nullable=False)
    granted_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
