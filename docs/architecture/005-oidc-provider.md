# ADR 005: OpenID Connect provider

- Status: **Proposed** (design only; nothing implemented)
- Date: 2026-11-06
- Inputs: [IdP architecture research](../research/idp-architecture.md), ADR 002/003 (sessions, RBAC, MFA)

## Context
IdentityForge authenticates users (password, TOTP, passkeys) and keeps server-side sessions, but cannot yet act as an identity provider for other applications. This ADR designs an OIDC Provider (OP) so that first-party and third-party apps can sign users in with IdentityForge.

## Goals
- Authorization Code flow with **PKCE required for every client**; exact-match redirect URIs.
- Discovery, JWKS, UserInfo; ID tokens with honest `auth_time`, `amr`, `acr`.
- Rotating refresh tokens with reuse detection; revocation and introspection.
- Admin UI to register/manage clients; user-visible consent and revocation.
- Pass the OpenID conformance suite (Basic OP, Config OP) before any release claim.

## Non-goals (this ADR)
Implicit and password grants (excluded per RFC 9700 direction), dynamic client registration, SAML, SCIM, multi-tenancy, DPoP/mTLS, `private_key_jwt` (listed as later), device flow.

## Decisions

### 1. Issuer and origin
One public issuer URL (`OIDC_ISSUER`, https in production). Endpoints live under that origin: `/.well-known/openid-configuration`, `/oauth/authorize`, `/oauth/token`, `/oauth/userinfo`, `/oauth/revoke`, `/oauth/introspect`, `/oauth/jwks`, `/oauth/logout`. Open question: the API and the UI are on different origins in dev; production should front both behind one hostname.

### 2. Login and consent flow (server-stored pending request)
`/oauth/authorize` validates client, redirect URI, scopes, PKCE challenge, then **stores the request server-side** and redirects to the UI with only an opaque `request_id`. The UI uses the existing session (SameSite=Lax cookie works for top-level navigation), logs in if needed, shows consent, and posts the decision to the API (CSRF protected). The server then issues the code from the stored request, so parameters cannot be tampered with between login and consent (Hydra-style).
- `prompt=none|login|consent`, `max_age`, `acr_values` honoured; `max_age`/`prompt=login` evaluated against the session's `auth_time`.
- First-party clients may skip consent (flag on client, admin-only). Open question for the owner.

### 3. Session changes required first (prerequisite milestone)
Add to the session: `auth_time` and `amr` (set in `complete_login`, which today only audits the method string). Map: password→`pwd`, TOTP→`otp`, passkey→`hwk`+`user`/`mfa` as applicable, recovery code→`otp`/`pwd` as applicable. `acr`: define two levels, e.g. `urn:identityforge:acr:1` (single factor) and `:2` (MFA or passkey); document that `amr` is the detailed truth. Step-up is a fresh authentication that updates `auth_time`/`amr` on the session.

### 4. Tokens
- **Code:** random, single use, ~60 s, bound to client, redirect URI, PKCE challenge; stored hashed (SHA-256).
- **ID token:** signed JWT (RS256 for interop; revisit ES256), claims per requested scopes: `sub` (stable, non-email user identifier), `iss`, `aud`, `exp`, `iat`, `nonce`, `auth_time`, `amr`, `acr`, plus `email`, `name`, `groups` by scope.
- **Access token:** opaque by default (introspection, easy revocation), ~10 min. JWT access tokens (RFC 9068) are an option if resource servers need offline validation. Open question.
- **Refresh token:** opaque, hashed at rest, rotating; each belongs to a family; reuse of a rotated token revokes the whole family and is audited. Absolute lifetime bounded by the originating session policy.

### 5. Signing keys
Keys generated in-app, private key encrypted at rest (reuse the Fernet approach with a separate `OIDC_KEY_ENCRYPTION_KEY`), `kid` published in JWKS. Rotation publishes the new key, signs with it after a delay, and keeps the old public key until `max token TTL + clock skew + client cache TTL`. Rotation is an admin action and audited; a CLI path for emergency rotation.

### 6. Data model (Alembic 0007+)
`oidc_clients` (id, secret hash or none for public, redirect URIs, allowed scopes, first-party flag, status), `oidc_pending_requests`, `oidc_codes`, `oidc_consents` (user, client, scopes, revoked_at), `oidc_refresh_tokens` (family id, parent, used_at, revoked_at), `oidc_signing_keys`. Add `auth_time`, `amr` to `sessions`. Audit actions are plain strings, so no enum migration; new actions: `OIDC_CLIENT_CREATED/UPDATED/DELETED`, `OIDC_CONSENT_GRANTED/REVOKED`, `OIDC_TOKEN_ISSUED`, `OIDC_REFRESH_REUSE_DETECTED`, `OIDC_KEY_ROTATED`.

### 7. Security controls
Exact redirect match; `state`/`nonce` supported; PKCE S256 only; client secrets hashed with Argon2id; constant-time compares; no tokens in logs; token endpoint rate limited (Redis); no CORS credentials on token/userinfo/jwks (separate CORS policy from the credentialed UI API); `frame-ancestors 'none'` on login/consent pages; admin client management behind `require_admin` plus MFA policy; deny-by-default scope allow-list per client.

### 8. Library choice
"Mature cryptographic libraries only." JWT/JWK handling via a maintained library (`joserfc` or `authlib.jose`). Authlib's framework-agnostic OAuth server pieces exist, but its FastAPI integration is not first-class and is **unverified here**. Plan a one-day spike: implement authorize+token with Authlib vs. hand-rolled on joserfc, then decide. Do not hand-roll signature/crypto primitives under any option.

## Milestones
1. Session `auth_time`/`amr` + client registry + discovery/JWKS.
2. Authorize/consent/token (code+PKCE), ID tokens, UserInfo.
3. Refresh rotation + reuse detection, revocation, introspection.
4. Logout (RP-initiated), `max_age`/`prompt`/`acr_values`, consent management UI.
5. Admin client UI, audit views, key rotation UI.
6. Conformance suite run, interop test with a real RP, security review.
Later: `private_key_jwt`, client credentials, per-app sign-in policy, DPoP, SAML/SCIM.

## Testing
API integration tests for every denial path (bad redirect, missing PKCE, code replay, refresh reuse, expired code, scope escalation); Playwright flow with a test RP; OpenID conformance suite; negative tests for CORS and cookie behaviour.

## Open questions for the owner
1. Which apps will be the first relying parties, and are any first-party (skip consent)?
2. Production hostname/TLS: single origin for UI and API?
3. Opaque vs JWT access tokens?
4. Need client-credentials (service-to-service) soon?
5. Single tenant forever, or plan for tenancy now?
6. RS256 (interop) or ES256?

## Risks
Subtle protocol bugs (mitigate: conformance suite, spike, review); session model change affects every login path; key-management mistakes; scope creep toward a full IdP. Source quality for some research claims is medium, so verify against the RFCs during implementation.
