"""SWA tables (ADR 012)."""

from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, LargeBinary, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from backend.app.db import Base
from backend.app.tenancy import TenantOwned


def _now():
    return datetime.now(timezone.utc)


class SwaConfig(TenantOwned, Base):
    """The SWA facet of an application: where the login form posts to and which fields it expects."""

    __tablename__ = "swa_configs"
    __table_args__ = (CheckConstraint("username_source IN ('user','email','username')", name="ck_swa_username_source"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    application_id = Column(Integer, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, unique=True)
    login_url = Column(String(2000), nullable=False)  # the only place a credential is ever sent
    username_field = Column(String(64), nullable=False)
    password_field = Column(String(64), nullable=False)
    extra_fields = Column(JSONB, nullable=False, default=list)  # fixed hidden fields: [{"name": "...", "value": "..."}]
    username_source = Column(String(10), nullable=False, default="user")  # user types it | the user's email | the user's username
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class SwaCredential(TenantOwned, Base):
    """One user's account at one application. The password only exists encrypted (AES-GCM, bound to tenant/app/user)."""

    __tablename__ = "swa_credentials"
    __table_args__ = (UniqueConstraint("application_id", "user_id", name="uq_swa_credentials_app_user"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    application_id = Column(Integer, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    username = Column(String(255), nullable=True)  # only when the user types it; otherwise derived from the profile at launch
    secret = Column(LargeBinary, nullable=False)
    key_id = Column(String(8), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
