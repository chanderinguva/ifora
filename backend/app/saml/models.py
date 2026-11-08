"""SAML 2.0 IdP tables (ADR 011)."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from backend.app.db import Base
from backend.app.tenancy import TenantOwned


def _now():
    return datetime.now(timezone.utc)


class SamlProvider(TenantOwned, Base):
    """The SAML facet of an application: who the service provider is and what we put in its assertion."""

    __tablename__ = "saml_providers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sp_entity_id", name="uq_saml_providers_tenant_entity"),
        CheckConstraint("name_id_format IN ('email','persistent','username','attribute')", name="ck_saml_name_id_format"),
        CheckConstraint("signing IN ('assertion','response','both')", name="ck_saml_signing"),
        CheckConstraint("validity_seconds BETWEEN 60 AND 3600", name="ck_saml_validity"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    application_id = Column(Integer, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, unique=True)
    sp_entity_id = Column(String(500), nullable=False)
    acs_url = Column(String(2000), nullable=False)  # the only place an assertion is ever sent
    audience = Column(String(500), nullable=True)  # defaults to the SP entity id
    name_id_format = Column(String(12), nullable=False, default="email")
    name_id_attribute = Column(String(80), nullable=True)  # when name_id_format = attribute
    signing = Column(String(10), nullable=False, default="both")
    attribute_mappings = Column(JSONB, nullable=False, default=list)  # [{"name": "...", "source": "email|groups|attr:key|..."}]
    sp_cert = Column(Text, nullable=True)  # PEM; verifies signed AuthnRequests
    require_signed_requests = Column(Boolean, nullable=False, default=False, server_default="false")
    default_relay_state = Column(String(512), nullable=True)
    validity_seconds = Column(Integer, nullable=False, default=300, server_default="300")
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class SamlSigningKey(TenantOwned, Base):
    __tablename__ = "saml_signing_keys"
    __table_args__ = (CheckConstraint("status IN ('active','retired')", name="ck_saml_key_status"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    private_key_enc = Column(Text, nullable=False)  # Fernet(OIDC_KEY_ENCRYPTION_KEY)
    cert_pem = Column(Text, nullable=False)
    not_after = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(8), nullable=False, default="active")
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class SamlPendingRequest(TenantOwned, Base):
    """A validated AuthnRequest parked while the user signs in. The browser only holds the opaque id."""

    __tablename__ = "saml_pending_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_hash = Column(String(64), nullable=False, unique=True)
    provider_id = Column(Integer, ForeignKey("saml_providers.id", ondelete="CASCADE"), nullable=False, index=True)
    in_response_to = Column(String(256), nullable=False)
    relay_state = Column(String(512), nullable=True)
    auth_after = Column(DateTime(timezone=True), nullable=True)  # ForceAuthn: the session must be newer than this
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    decided_at = Column(DateTime(timezone=True), nullable=True)
