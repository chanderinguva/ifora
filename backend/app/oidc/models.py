"""OIDC persistence. Signing keys first (ADR 005 §6); clients, codes and tokens follow in later milestones."""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB

from backend.app.db import Base
from backend.app.tenancy import TenantOwned


def _now() -> datetime:
    return datetime.now(timezone.utc)


class KeyStatus:
    PENDING = "pending"    # published in JWKS so relying parties can cache it; not signing yet
    ACTIVE = "active"      # the one key that signs new tokens
    RETIRED = "retired"    # no longer signs; stays in JWKS until retire_at so issued tokens still verify
    EXPIRED = "expired"    # overlap over; removed from JWKS, private key wiped
    REVOKED = "revoked"    # emergency rotation: removed from JWKS immediately, private key wiped


class SigningKey(TenantOwned, Base):
    __tablename__ = "oidc_signing_keys"
    __table_args__ = (
        UniqueConstraint("tenant_id", "kid", name="uq_oidc_signing_keys_tenant_kid"),
        # at most one signing key per tenant, enforced by the database (guards concurrent bootstrap)
        Index("uq_oidc_signing_keys_one_active", "tenant_id", unique=True, postgresql_where=text("status = 'active'")),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    kid = Column(String(64), nullable=False)  # RFC 7638 JWK thumbprint
    alg = Column(String(16), nullable=False)  # RS256 now; ES256 later (per-key, so keys of both can coexist)
    status = Column(String(16), nullable=False, index=True)
    # Fernet(OIDC_KEY_ENCRYPTION_KEY) of the PEM private key; NULL once expired/revoked. Never returned by any API.
    private_pem_encrypted = Column(Text, nullable=True)
    public_jwk = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    activate_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    retire_at = Column(DateTime(timezone=True), nullable=True)  # leave JWKS at this time once retired

    def to_admin_dict(self) -> dict:
        """Metadata only; no key material beyond the public JWK."""
        return {
            "kid": self.kid,
            "alg": self.alg,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "activate_at": self.activate_at.isoformat(),
            "retire_at": self.retire_at.isoformat() if self.retire_at else None,
        }
