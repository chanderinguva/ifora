"""Per-user dashboard preferences: sections, favourites, recents (ADR 016)."""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint

from backend.app.db import Base
from backend.app.tenancy import TenantOwned


class UserAppSection(TenantOwned, Base):
    __tablename__ = "user_app_sections"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_user_app_sections_name"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(40), nullable=False)
    position = Column(Integer, nullable=False, default=0)


class UserAppPref(TenantOwned, Base):
    __tablename__ = "user_app_prefs"
    __table_args__ = (UniqueConstraint("user_id", "application_id", name="uq_user_app_prefs_app"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    application_id = Column(Integer, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    favorite = Column(Boolean, nullable=False, default=False)
    section_id = Column(Integer, ForeignKey("user_app_sections.id", ondelete="SET NULL"), nullable=True)
    position = Column(Integer, nullable=False, default=0)
    last_launched_at = Column(DateTime(timezone=True), nullable=True)
    launch_count = Column(Integer, nullable=False, default=0)
