"""Application configuration using Pydantic Settings."""

import os
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Core settings
    SECRET_KEY: str = Field(..., min_length=32)
    ADMIN_SECRET_KEY: str = Field(..., min_length=32)
    # Fernet key (urlsafe base64, 32 bytes) used to encrypt TOTP secrets at rest.
    # Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    MFA_ENCRYPTION_KEY: str = Field(...)
    MFA_ISSUER: str = Field(default="IdentityForge")
    # Admins must have an authenticator app or a passkey before the admin API works for them.
    ADMIN_MFA_REQUIRED: bool = Field(default=True)
    # OIDC provider (ADR 005). The signing-key encryption key must be a *different* Fernet key from MFA_ENCRYPTION_KEY.
    OIDC_ISSUER: str = Field(default="http://localhost:8000")
    OIDC_KEY_ENCRYPTION_KEY: str = Field(default="")
    # Where /oauth/authorize sends the browser for login / consent (a page of the web UI).
    OIDC_LOGIN_UI_URL: str = Field(default="http://localhost:3000/oauth/authorize")
    OIDC_PENDING_REQUEST_TTL_SECONDS: int = Field(default=600)
    OIDC_CODE_TTL_SECONDS: int = Field(default=60)
    RATE_LIMIT_TOKEN_FAILURES: int = Field(default=20)
    RATE_LIMIT_TOKEN_WINDOW_SECONDS: int = Field(default=300)
    OIDC_RSA_KEY_BITS: int = Field(default=3072)
    OIDC_ID_TOKEN_TTL_SECONDS: int = Field(default=600)
    OIDC_ACCESS_TOKEN_TTL_SECONDS: int = Field(default=600)
    OIDC_CLOCK_SKEW_SECONDS: int = Field(default=60)
    OIDC_JWKS_CACHE_SECONDS: int = Field(default=300)
    # Edition feature flag: attribute-based group rules (Okta-style).
    GROUP_RULES_ENABLED: bool = Field(default=True)
    MFA_CHALLENGE_MINUTES: int = Field(default=5)
    MFA_CHALLENGE_MAX_ATTEMPTS: int = Field(default=5)

    # WebAuthn / passkeys. RP ID must be the registrable domain of the *frontend* origin the
    # browser sees (e.g. "localhost", or "example.com" for https://app.example.com);
    # origins must match exactly (scheme + host + port).
    WEBAUTHN_RP_ID: str = Field(default="localhost")
    WEBAUTHN_RP_NAME: str = Field(default="IdentityForge")
    WEBAUTHN_ORIGINS: List[str] = Field(default=["http://localhost:3000"])
    WEBAUTHN_CEREMONY_SECONDS: int = Field(default=300)
    ENVIRONMENT: str = Field(default="development")
    DEBUG: bool = Field(default=False)

    # Database
    DATABASE_URL: str = Field(..., env="DATABASE_URL")
    DATABASE_URL_ASYNC: str = Field(..., env="DATABASE_URL_ASYNC")

    # Redis
    REDIS_URL: str = Field(default="redis://localhost:6379/0")

    # Security
    SESSION_COOKIE_NAME: str = Field(default="identityforge_session")
    SESSION_COOKIE_SECURE: bool = Field(default=False)
    SESSION_COOKIE_SAMESITE: str = Field(default="lax")
    SESSION_LIFETIME_HOURS: int = Field(default=8)
    SESSION_IDLE_TIMEOUT_MINUTES: int = Field(default=30)

    # Rate limiting
    MAX_LOGIN_ATTEMPTS: int = Field(default=5)
    LOGIN_LOCKOUT_MINUTES: int = Field(default=15)
    # Per-client-IP throttle on failed logins / bootstrap attempts (Redis, fixed window)
    RATE_LIMIT_LOGIN_FAILURES: int = Field(default=10)
    RATE_LIMIT_LOGIN_WINDOW_SECONDS: int = Field(default=300)
    RATE_LIMIT_BOOTSTRAP_ATTEMPTS: int = Field(default=5)
    RATE_LIMIT_BOOTSTRAP_WINDOW_SECONDS: int = Field(default=900)

    # Admin
    ADMIN_EMAIL: str = Field(default="admin@identityforge.local")
    ADMIN_FIRST_NAME: str = Field(default="System")
    ADMIN_LAST_NAME: str = Field(default="Administrator")

    # API
    API_V1_PREFIX: str = Field(default="/api/v1")
    CORS_ORIGINS: List[str] = Field(default=["http://localhost:3000", "http://localhost:8000"])

    @field_validator("MFA_ENCRYPTION_KEY")
    @classmethod
    def valid_fernet_key(cls, v):
        from cryptography.fernet import Fernet

        try:
            Fernet(v.encode())
        except Exception as e:  # noqa: BLE001
            raise ValueError("MFA_ENCRYPTION_KEY must be a valid Fernet key") from e
        return v

    @field_validator("WEBAUTHN_ORIGINS", mode="before")
    @classmethod
    def parse_webauthn_origins(cls, v):
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()