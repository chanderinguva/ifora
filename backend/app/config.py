"""Application configuration using Pydantic Settings."""

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
    MFA_ISSUER: str = Field(default="Ifora")
    # Admins must have an authenticator app or a passkey before the admin API works for them.
    ADMIN_MFA_REQUIRED: bool = Field(default=True)
    # OIDC provider (ADR 005). The signing-key encryption key must be a *different* Fernet key from MFA_ENCRYPTION_KEY.
    OIDC_ISSUER: str = Field(default="http://localhost:8000")
    OIDC_KEY_ENCRYPTION_KEY: str = Field(default="")
    # Stored sign-in credentials for SWA applications (ADR 012). 32 random bytes, url-safe base64; unset = SWA credentials disabled.
    # Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    SWA_ENCRYPTION_KEY: str = Field(default="")
    SWA_ENCRYPTION_KEY_PREVIOUS: str = Field(default="")  # keep the retired key here while rows are re-encrypted on use
    SWA_FRESH_AUTH_SECONDS: int = Field(default=900)  # a stored credential is only released if the user signed in this recently
    SAML_ENTITY_ID: str = Field(default="")  # IdP entity id; default <OIDC_ISSUER>/saml/idp
    # Optional dedicated Fernet key for SAML signing-key encryption (IFORA-25). Unset = a subkey derived from
    # OIDC_KEY_ENCRYPTION_KEY (separate subkey, same master secret). Set it so compromise of the OIDC secret does not expose SAML keys.
    SAML_KEY_ENCRYPTION_KEY: str = Field(default="")
    SAML_CERT_VALIDITY_DAYS: int = Field(default=730, ge=30, le=3650)  # lifetime of a newly issued SAML signing certificate
    SAML_CERT_WARN_DAYS: int = Field(default=60, ge=1, le=365)  # the admin API flags a certificate this close to expiry
    SAML_PENDING_TTL_SECONDS: int = Field(default=600)  # how long a parked AuthnRequest waits for the user to sign in
    # Where /oauth/authorize sends the browser for login / consent (a page of the web UI).
    OIDC_LOGIN_UI_URL: str = Field(default="http://localhost:3000/oauth/authorize")
    OIDC_LOGOUT_UI_URL: str = Field(default="http://localhost:3000/oauth/logout")
    OIDC_PENDING_REQUEST_TTL_SECONDS: int = Field(default=600)
    OIDC_CODE_TTL_SECONDS: int = Field(default=60)
    OIDC_REFRESH_IDLE_DAYS: int = Field(default=7)       # unused for this long = expired
    OIDC_REFRESH_ABSOLUTE_DAYS: int = Field(default=30)  # hard cap on a family, however often it is used
    RATE_LIMIT_AUTHORIZE_REQUESTS: int = Field(default=120)   # /oauth/authorize hits per client IP per window
    RATE_LIMIT_AUTHORIZE_WINDOW_SECONDS: int = Field(default=60)
    RATE_LIMIT_TOKEN_FAILURES: int = Field(default=20)
    RATE_LIMIT_TOKEN_WINDOW_SECONDS: int = Field(default=300)
    OIDC_RSA_KEY_BITS: int = Field(default=3072)
    OIDC_SIGNING_ALG: str = Field(default="RS256")  # algorithm of newly created signing keys: RS256 | ES256
    OIDC_ID_TOKEN_TTL_SECONDS: int = Field(default=600)
    OIDC_ACCESS_TOKEN_TTL_SECONDS: int = Field(default=600)
    OIDC_CLOCK_SKEW_SECONDS: int = Field(default=60)
    OIDC_JWKS_CACHE_SECONDS: int = Field(default=300)
    # Edition feature flag: attribute-based group rules (Okta-style).
    GROUP_RULES_ENABLED: bool = Field(default=True)
    # Activating a rule in a directory larger than this is finished by the worker in batches instead of inside the request.
    GROUP_RULES_SYNC_MAX_USERS: int = Field(default=500)
    GROUP_RULES_BATCH_SIZE: int = Field(default=200)
    # Recipe engine (ADR 008). Kill switch + limits. RECIPE_ENCRYPTION_KEY is a third, separate Fernet key;
    # empty = connections (stored secrets) and webhook triggers are unavailable.
    RECIPES_JOB_RETENTION_DAYS: int = Field(default=30)  # finished jobs and their step history are deleted after this many days (0 = keep)
    RECIPES_ENABLED: bool = Field(default=True)
    RECIPE_ENCRYPTION_KEY: str = Field(default="")
    RECIPE_SECRET_PROVIDER: str = Field(default="fernet", pattern="^(fernet|openbao)$")
    RECIPE_ENCRYPTION_KEY_PREVIOUS: str = Field(default="")
    RECIPE_OPENBAO_URL: str = Field(default="")
    RECIPE_OPENBAO_KEY: str = Field(default="ifora-connections")
    RECIPE_OPENBAO_CA_FILE: str = Field(default="")
    RECIPE_OPENBAO_ROLE_ID_FILE: str = Field(default="")
    RECIPE_OPENBAO_SECRET_ID_FILE: str = Field(default="")
    RECIPE_OAUTH_CALLBACK_URL: str = Field(default="")  # exact public callback URL, never inferred from Host
    RECIPES_MAX_STEPS_PER_JOB: int = Field(default=500)  # executed steps, loop iterations included
    RECIPES_MAX_RUNTIME_SECONDS: int = Field(default=900)
    RECIPES_MAX_EVENT_DEPTH: int = Field(default=3)
    RECIPES_MAX_CONCURRENT_PER_RECIPE: int = Field(default=5)
    RECIPES_LEASE_SECONDS: int = Field(default=120)
    RECIPES_RETRY_BASE_SECONDS: int = Field(default=5)
    RECIPES_WORKER_BATCH: int = Field(default=20)
    RECIPES_HTTP_TIMEOUT_SECONDS: int = Field(default=10)
    RECIPES_HTTP_MAX_RESPONSE_BYTES: int = Field(default=1_000_000)
    # Prometheus scrape token (bearer). Unset = the /metrics endpoint does not exist. Use 32+ random characters.
    METRICS_TOKEN: str = Field(default="")
    PROVISIONING_ENABLED: bool = Field(default=True)
    PROVISIONING_BATCH: int = Field(default=25)  # tasks claimed per tenant per worker pass
    PROVISIONING_PER_APP_BATCH: int = Field(default=10)  # ...and at most this many per app (do not hammer one app)
    PROVISIONING_MAX_ATTEMPTS: int = Field(default=6)
    PROVISIONING_LEASE_SECONDS: int = Field(default=120)
    RECIPES_HTTP_ALLOWED_HOSTS: str = Field(default="")  # comma separated; empty = any public host
    RECIPES_WEBHOOK_MAX_BODY_BYTES: int = Field(default=65536)
    RECIPES_WEBHOOK_REPLAY_SECONDS: int = Field(default=300)
    # Slack message shortcut -> Ifora Discovery. Disabled until every required secret and allow-list is configured.
    SLACK_IDEA_CAPTURE_ENABLED: bool = Field(default=False)
    SLACK_IDEA_SIGNING_SECRET: str = Field(default="")
    SLACK_IDEA_ALLOWED_TEAM_ID: str = Field(default="")
    SLACK_IDEA_ALLOWED_USER_IDS: str = Field(default="")
    SLACK_IDEA_DELIVERY_TIMEOUT_SECONDS: float = Field(default=5.0, gt=0, le=30)
    IFORA_DISCOVERY_INGEST_URL: str = Field(default="")
    IFORA_DISCOVERY_INGEST_TOKEN: str = Field(default="")
    IFORA_DISCOVERY_SITES_AUTH_TOKEN: str = Field(default="")
    RECIPES_MAX_RECIPES: int = Field(default=100)
    SCIM_ACCEPT_LEGACY_GROUP_IDS: bool = Field(default=True)  # accept integer group ids on lookup (new ids are opaque UUIDs)
    RECIPES_DEFAULT_RATE_PER_HOUR: int = Field(default=0)  # live jobs per recipe per rolling hour when the recipe sets none (0 = unlimited)
    RECIPES_ALERT_WINDOW_MINUTES: int = Field(default=60)
    RECIPES_ALERT_MIN_JOBS: int = Field(default=5)  # finished jobs in the window before a failure rate means anything
    RECIPES_ALERT_FAILURE_RATE: float = Field(default=0.5)
    # Outbound email for the send_email step (empty SMTP_HOST = disabled). Recipients must be existing users or in an allowed domain.
    SMTP_HOST: str = Field(default="")
    SMTP_PORT: int = Field(default=587)
    SMTP_USERNAME: str = Field(default="")
    SMTP_PASSWORD: str = Field(default="")
    SMTP_FROM: str = Field(default="")
    SMTP_FROM_NAME: str = Field(default="")  # display name shown as "Name <address>"
    SMTP_STARTTLS: bool = Field(default=True)
    SMTP_IMPLICIT_TLS: bool = Field(default=False)  # true for port 465 (SMTPS); STARTTLS is then not used
    # New users get username "first.last" (numeric suffix on conflict) and primary email "<username>@<this domain>".
    # Empty = no automatic email: the admin must type one. See docs/architecture/023-user-identity-naming.md.
    PRIMARY_EMAIL_DOMAIN: str = Field(default="")
    # Links in invite / password-reset emails point here (the web app's public URL).
    PUBLIC_APP_URL: str = Field(default="http://localhost:3000")
    PASSWORD_RESET_MINUTES: int = Field(default=30)
    INVITE_HOURS: int = Field(default=72)
    RECIPES_EMAIL_ALLOWED_DOMAINS: str = Field(default="")  # comma separated, in addition to addresses of existing users
    RECIPES_MAX_EMAILS_PER_JOB: int = Field(default=25)
    MFA_CHALLENGE_MINUTES: int = Field(default=5)
    MFA_CHALLENGE_MAX_ATTEMPTS: int = Field(default=5)

    # WebAuthn / passkeys. RP ID must be the registrable domain of the *frontend* origin the
    # browser sees (e.g. "localhost", or "example.com" for https://app.example.com);
    # origins must match exactly (scheme + host + port).
    WEBAUTHN_RP_ID: str = Field(default="localhost")
    WEBAUTHN_RP_NAME: str = Field(default="Ifora")
    WEBAUTHN_ORIGINS: List[str] = Field(default=["http://localhost:3000"])
    WEBAUTHN_CEREMONY_SECONDS: int = Field(default=300)

    # Sign-in through Cloudflare Access (demo environments). Off by default. When on, a request that carries a valid
    # Access identity token (Cf-Access-Jwt-Assertion) for ACCESS_AUD from ACCESS_TEAM_DOMAIN can start a session for
    # the matching non-admin account; unknown emails get an account when ACCESS_SSO_AUTO_CREATE is true.
    # Let admins who must enrol a first factor have the one-time enrolment code emailed to their own
    # address (instead of asking a super admin / operator). Never applies to super admins.
    ENROLLMENT_CODE_EMAIL: bool = Field(default=False)
    ACCESS_SSO_ENABLED: bool = Field(default=False)
    ACCESS_TEAM_DOMAIN: str = Field(default="")  # e.g. "myteam.cloudflareaccess.com" (no scheme)
    ACCESS_AUD: str = Field(default="")  # the Access application's audience (AUD) tag
    ACCESS_SSO_AUTO_CREATE: bool = Field(default=True)
    # Keep the Cloudflare Access allowlist in step with the users: inviting someone adds their email to the Access
    # policy below, deleting them removes it. Needs a Cloudflare API token limited to "Access: Apps and Policies: Edit".
    # All four must be set to switch it on.
    ACCESS_ALLOWLIST_TOKEN: str = Field(default="")
    ACCESS_ALLOWLIST_ACCOUNT_ID: str = Field(default="")
    ACCESS_ALLOWLIST_APP_ID: str = Field(default="")
    ACCESS_ALLOWLIST_POLICY_ID: str = Field(default="")
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
    # Tenant resolution (IFORA-18): "single" = the seeded default tenant (today's behaviour); "host" = the tenant whose
    # slug is the first label of the request Host under TENANT_BASE_DOMAIN. Unresolvable -> request refused (fail closed).
    TENANT_RESOLUTION: str = Field(default="single", pattern="^(single|host)$")
    TENANT_BASE_DOMAIN: str = Field(default="")
    RATE_LIMIT_FAIL_CLOSED: bool = Field(default=True)  # Redis down: credential endpoints answer 503 (false = fail open, rollback)
    RATE_LIMIT_LOCKED_GUESSES: int = Field(default=20)  # wrong passwords per locked account from known addresses per window
    RATE_LIMIT_LOCKED_WINDOW_SECONDS: int = Field(default=900)
    RATE_LIMIT_RESET_EMAIL_CEILING: int = Field(default=30)  # reset requests per email per hour, all addresses together
    RATE_LIMIT_MFA_FAILURES: int = Field(default=10)  # wrong passwords/codes on account-security endpoints per user per window
    RATE_LIMIT_MFA_WINDOW_SECONDS: int = Field(default=900)
    # Admin step-up (IFORA-33): sensitive admin actions need an MFA proof this recent (a fresh MFA sign-in counts). Applies where
    # ADMIN_MFA_REQUIRED is on; API tokens are exempt (they never hold a session factor).
    ADMIN_STEPUP_MINUTES: int = Field(default=10, ge=1, le=240)
    RATE_LIMIT_POLICY_SIMULATE: int = Field(default=30)  # policy simulations per admin per minute
    RATE_LIMIT_BOOTSTRAP_ATTEMPTS: int = Field(default=5)
    RATE_LIMIT_BOOTSTRAP_WINDOW_SECONDS: int = Field(default=900)

    # SCIM server (ADR 007)
    SCIM_RATE_LIMIT_FAILURES: int = Field(default=20)      # failed bearer tokens per client IP per window
    SCIM_RATE_LIMIT_WINDOW_SECONDS: int = Field(default=300)
    SCIM_RATE_LIMIT_REQUESTS_PER_MINUTE: int = Field(default=1200)  # per token

    # Admin
    ADMIN_EMAIL: str = Field(default="admin@identityforge.local")
    ADMIN_FIRST_NAME: str = Field(default="System")
    ADMIN_LAST_NAME: str = Field(default="Administrator")

    # API
    API_V1_PREFIX: str = Field(default="/api/v1")
    CORS_ORIGINS: List[str] = Field(default=["http://localhost:3000", "http://localhost:8000"])

    @field_validator("PRIMARY_EMAIL_DOMAIN")
    @classmethod
    def _primary_domain(cls, v: str) -> str:
        import re

        v = v.strip().lower().lstrip("@")
        if v and not re.fullmatch(r"(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", v):
            raise ValueError("PRIMARY_EMAIL_DOMAIN must be a domain name such as example.com")
        return v

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
