"""Application tables (ADR 010)."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, LargeBinary, String, UniqueConstraint, text

from backend.app.db import Base
from backend.app.tenancy import TenantOwned

SIGN_ON_MODES = ("none", "bookmark", "oidc", "saml")  # swa arrives with its own milestone


def _now():
    return datetime.now(timezone.utc)


class Application(TenantOwned, Base):
    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_applications_tenant_name"),
        CheckConstraint("sign_on_mode IN ('none','bookmark','oidc','saml')", name="ck_applications_sign_on_mode"),
        CheckConstraint("status IN ('active','inactive')", name="ck_applications_status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    public_id = Column(String(36), nullable=False, unique=True)
    name = Column(String(100), nullable=False)
    description = Column(String(500), nullable=True)
    sign_on_mode = Column(String(16), nullable=False, default="none")  # none = provisioning/assignment only
    launch_url = Column(String(2000), nullable=True)  # what the tile opens (bookmark URL, or an OIDC app's own sign-in URL)
    status = Column(String(10), nullable=False, default="active")
    visible = Column(Boolean, nullable=False, default=True, server_default="true")  # show a tile in My apps
    require_assignment = Column(Boolean, nullable=False, default=True, server_default="true")  # OIDC: unassigned users are refused
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class ApplicationAssignment(TenantOwned, Base):
    """A user, or every member of a group, is entitled to the application (sign-on tile, OIDC access, provisioning)."""

    __tablename__ = "application_assignments"
    __table_args__ = (
        CheckConstraint("(user_id IS NULL) <> (group_id IS NULL)", name="ck_app_assignment_one_subject"),
        Index("uq_app_assign_user", "application_id", "user_id", unique=True, postgresql_where=text("user_id IS NOT NULL")),
        Index("uq_app_assign_group", "application_id", "group_id", unique=True, postgresql_where=text("group_id IS NOT NULL")),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    application_id = Column(Integer, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=True, index=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class ApplicationIcon(TenantOwned, Base):
    """Tile logo, kept apart from the application row so list queries never load image bytes. Raster only (PNG/JPEG/WebP,
    checked by signature): no SVG, which can carry script."""

    __tablename__ = "application_icons"

    application_id = Column(Integer, ForeignKey("applications.id", ondelete="CASCADE"), primary_key=True)
    content_type = Column(String(20), nullable=False)
    data = Column(LargeBinary, nullable=False)
    sha256 = Column(String(64), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now)
