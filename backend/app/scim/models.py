"""SCIM tables: provisioning bearer tokens and externalId links (ADR 007)."""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB

from backend.app.db import Base
from backend.app.tenancy import TenantOwned


def _now():
    return datetime.now(timezone.utc)


class ScimToken(TenantOwned, Base):
    """Bearer token an IdP uses for one tenant. Only a keyed hash is stored; the token is shown once."""

    __tablename__ = "scim_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    token_prefix = Column(String(16), nullable=False)  # non-secret, to tell tokens apart
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    read_only = Column(Boolean, nullable=False, default=False, server_default="false")  # GET/HEAD only
    users_only = Column(Boolean, nullable=False, default=False, server_default="false")  # /Groups is off limits
    allowed_cidrs = Column(JSONB, nullable=True)  # None/empty = any source address
    replaced_by_id = Column(Integer, nullable=True)  # set when this token was rotated; it keeps working until its (shortened) expiry
    hard_delete_after_days = Column(Integer, nullable=True)  # users this token deactivated are deleted after N days (None = never)

    @property
    def status(self) -> str:
        if self.revoked_at is not None:
            return "revoked"
        if self.expires_at is not None and self.expires_at <= _now():
            return "expired"
        return "active"

    def to_dict(self) -> dict:
        iso = lambda d: d.isoformat() if d else None  # noqa: E731
        return {
            "id": self.id,
            "name": self.name,
            "token_prefix": self.token_prefix,
            "status": self.status,
            "created_at": iso(self.created_at),
            "expires_at": iso(self.expires_at),
            "revoked_at": iso(self.revoked_at),
            "last_used_at": iso(self.last_used_at),
            "read_only": bool(self.read_only),
            "users_only": bool(self.users_only),
            "allowed_cidrs": list(self.allowed_cidrs or []),
            "replaced_by_id": self.replaced_by_id,
            "hard_delete_after_days": self.hard_delete_after_days,
        }


class ScimDeprovisioned(TenantOwned, Base):
    """Which token deactivated a user and when, so an optional per-token retention policy can delete them later (S6)."""

    __tablename__ = "scim_deprovisioned"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="uq_scim_deprovisioned_tenant_user"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_id = Column(Integer, ForeignKey("scim_tokens.id", ondelete="CASCADE"), nullable=False)
    deactivated_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class ScimLink(TenantOwned, Base):
    """externalId of a provisioned user or group (kept out of the users/groups tables)."""

    __tablename__ = "scim_links"
    __table_args__ = (
        CheckConstraint("(user_id IS NOT NULL) <> (group_id IS NOT NULL)", name="ck_scim_links_one_target"),
        UniqueConstraint("tenant_id", "user_id", name="uq_scim_links_tenant_user"),
        UniqueConstraint("tenant_id", "group_id", name="uq_scim_links_tenant_group"),
        Index("uq_scim_links_user_external", "tenant_id", "external_id", unique=True,
              postgresql_where=text("user_id IS NOT NULL")),
        Index("uq_scim_links_group_external", "tenant_id", "external_id", unique=True,
              postgresql_where=text("group_id IS NOT NULL")),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=True)
    external_id = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
