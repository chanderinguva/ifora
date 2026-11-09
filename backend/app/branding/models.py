"""Organization branding and email templates (ADR 015)."""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, LargeBinary, String, Text, UniqueConstraint

from backend.app.db import Base
from backend.app.tenancy import TenantOwned


def _now():
    return datetime.now(timezone.utc)


class OrgBranding(TenantOwned, Base):
    """At most one row per tenant. Every field is optional; empty means the IdentityForge default."""

    __tablename__ = "org_branding"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_org_branding_tenant"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    display_name = Column(String(60), nullable=True)
    primary_color = Column(String(7), nullable=True)  # '#rrggbb'
    tagline = Column(String(160), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class OrgLogo(TenantOwned, Base):
    """Raster only (PNG/JPEG/WebP by signature): an SVG could carry script, and this image is served to anonymous visitors."""

    __tablename__ = "org_logos"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_org_logos_tenant"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    content_type = Column(String(20), nullable=False)
    data = Column(LargeBinary, nullable=False)
    sha256 = Column(String(64), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class EmailTemplate(TenantOwned, Base):
    """An administrator's override of a built-in email. No row = the built-in text."""

    __tablename__ = "email_templates"
    __table_args__ = (UniqueConstraint("tenant_id", "key", name="uq_email_templates_tenant_key"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(20), nullable=False)
    subject = Column(String(200), nullable=False)
    body = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now)
