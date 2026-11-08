"""OIDC persistence. Signing keys first (ADR 005 §6); clients, codes and tokens follow in later milestones."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
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


class OIDCClient(TenantOwned, Base):
    """A registered relying party / application (ADR 005 §7)."""

    __tablename__ = "oidc_clients"
    __table_args__ = (UniqueConstraint("tenant_id", "client_id", name="uq_oidc_clients_tenant_client_id"),
                      Index("uq_oidc_clients_application", "application_id", unique=True, postgresql_where=text("application_id IS NOT NULL")))

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(String(64), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(String(500), nullable=True)
    client_type = Column(String(16), nullable=False)  # public | confidential  (service clients: Phase 2)
    token_endpoint_auth_method = Column(String(32), nullable=False)  # none | client_secret_basic
    first_party = Column(Boolean, nullable=False, default=False, server_default="false")
    status = Column(String(16), nullable=False, default="active")  # active | disabled
    redirect_uris = Column(JSONB, nullable=False)
    post_logout_redirect_uris = Column(JSONB, nullable=False, default=list)
    allowed_scopes = Column(JSONB, nullable=False)
    jwks = Column(JSONB, nullable=True)  # public keys of a private_key_jwt client (inline: no remote fetching, so no SSRF)
    allowed_audiences = Column(JSONB, nullable=False, default=list, server_default="[]")  # service clients: resources they may request
    application_id = Column(Integer, ForeignKey("applications.id", ondelete="SET NULL"), nullable=True)  # the application this client signs users in to (ADR 010)
    initiate_login_uri = Column(String(2000), nullable=True)  # OIDC third-party initiated login: where My apps sends the user to start the flow
    access_token_format = Column(String(8), nullable=False, default="jwt", server_default="jwt")  # jwt | opaque (opaque = revocable, introspect only)
    grant_types = Column(JSONB, nullable=False)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class OIDCClientSecret(TenantOwned, Base):
    """Confidential-client secrets. Hash only; two may be active at once so rotation needs no downtime."""

    __tablename__ = "oidc_client_secrets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_pk = Column(Integer, ForeignKey("oidc_clients.id", ondelete="CASCADE"), nullable=False, index=True)
    secret_hash = Column(String(255), nullable=False)
    hint = Column(String(8), nullable=False)  # last characters, to tell secrets apart in the UI
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)


class PendingAuthRequest(TenantOwned, Base):
    """A validated /oauth/authorize request parked server-side while the user logs in / consents (ADR 005 §3).

    The browser only ever holds the opaque request id; every parameter used to mint the code comes from this row,
    so nothing can be altered between login and consent. Only a hash of the id is stored.
    """

    __tablename__ = "oidc_pending_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_hash = Column(String(64), nullable=False, unique=True)
    client_pk = Column(Integer, ForeignKey("oidc_clients.id", ondelete="CASCADE"), nullable=False, index=True)
    redirect_uri = Column(String(2000), nullable=False)
    scopes = Column(JSONB, nullable=False)
    state = Column(String(512), nullable=True)
    nonce = Column(String(512), nullable=True)
    code_challenge = Column(String(128), nullable=False)
    prompt = Column(String(32), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    decided_at = Column(DateTime(timezone=True), nullable=True)  # single use: set atomically on the first decision
    # prompt=login / max_age / acr_values: the session used to decide must have authenticated at or after this instant
    auth_after = Column(DateTime(timezone=True), nullable=True)


class OIDCConsent(TenantOwned, Base):
    """What a user allowed a client to do. First-party clients get an implicit row (granted_via='first_party')."""

    __tablename__ = "oidc_consents"
    __table_args__ = (UniqueConstraint("user_id", "client_pk", name="uq_oidc_consents_user_client"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    client_pk = Column(Integer, ForeignKey("oidc_clients.id", ondelete="CASCADE"), nullable=False, index=True)
    scopes = Column(JSONB, nullable=False)
    granted_via = Column(String(16), nullable=False)  # user | first_party
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    revoked_at = Column(DateTime(timezone=True), nullable=True)


class AuthorizationCode(TenantOwned, Base):
    """Single-use code minted from a decided request: hashed at rest, ≤60 s, bound to client, redirect URI and PKCE."""

    __tablename__ = "oidc_codes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code_hash = Column(String(64), nullable=False, unique=True)
    client_pk = Column(Integer, ForeignKey("oidc_clients.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    redirect_uri = Column(String(2000), nullable=False)
    scopes = Column(JSONB, nullable=False)
    nonce = Column(String(512), nullable=True)
    code_challenge = Column(String(128), nullable=False)
    auth_time = Column(DateTime(timezone=True), nullable=False)
    amr = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)


class RefreshToken(TenantOwned, Base):
    """Opaque rotating refresh token (ADR 005 §5). Only a hash is stored. Each use spends the token and issues its
    successor in the same family; presenting a spent token means it leaked, so the whole family is revoked."""

    __tablename__ = "oidc_refresh_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    token_hash = Column(String(64), nullable=False, unique=True)
    family_id = Column(String(36), nullable=False, index=True)
    parent_id = Column(Integer, nullable=True)
    code_id = Column(Integer, ForeignKey("oidc_codes.id", ondelete="SET NULL"), nullable=True, index=True)
    client_pk = Column(Integer, ForeignKey("oidc_clients.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    scopes = Column(JSONB, nullable=False)
    auth_time = Column(DateTime(timezone=True), nullable=False)
    amr = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    expires_at = Column(DateTime(timezone=True), nullable=False)           # idle limit, slides on rotation
    absolute_expires_at = Column(DateTime(timezone=True), nullable=False)  # family hard limit, never extended
    used_at = Column(DateTime(timezone=True), nullable=True)               # rotated away
    revoked_at = Column(DateTime(timezone=True), nullable=True)


class AccessToken(TenantOwned, Base):
    """Opaque access token (clients with access_token_format = "opaque"). Only a hash is stored. Unlike a JWT it can be
    revoked at once (/oauth/revoke) and is verified by looking it up (userinfo, introspection)."""

    __tablename__ = "oidc_access_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    token_hash = Column(String(64), nullable=False, unique=True)
    client_pk = Column(Integer, ForeignKey("oidc_clients.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)  # null: client credentials
    sub = Column(String(64), nullable=False)
    audience = Column(String(255), nullable=False)
    scopes = Column(JSONB, nullable=False)
    auth_time = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
