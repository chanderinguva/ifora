"""Admin API tokens (ADR 024). Only a keyed hash is stored; the token is shown once."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB

from backend.app.db import Base
from backend.app.tenancy import TenantOwned


def _now():
    return datetime.now(timezone.utc)


class ApiToken(TenantOwned, Base):
    __tablename__ = "api_tokens"
    __table_args__ = (Index("uq_api_tokens_user_name_live", "user_id", "name", unique=True, postgresql_where=text("revoked_at IS NULL")),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)  # the administrator it acts as
    name = Column(String(100), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    token_prefix = Column(String(16), nullable=False)
    read_only = Column(Boolean, nullable=False, default=False, server_default="false")
    allowed_cidrs = Column(JSONB, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    last_used_ip = Column(String(45), nullable=True)

    @property
    def status(self) -> str:
        if self.revoked_at is not None:
            return "revoked"
        if self.expires_at <= _now():
            return "expired"
        return "active"

    def to_dict(self) -> dict:
        iso = lambda d: d.isoformat() if d else None  # noqa: E731
        return {
            "id": self.id, "name": self.name, "user_id": self.user_id, "token_prefix": self.token_prefix, "status": self.status,
            "read_only": bool(self.read_only), "allowed_cidrs": list(self.allowed_cidrs or []),
            "created_at": iso(self.created_at), "expires_at": iso(self.expires_at), "revoked_at": iso(self.revoked_at),
            "last_used_at": iso(self.last_used_at), "last_used_ip": self.last_used_ip,
        }
