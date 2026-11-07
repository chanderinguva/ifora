# OIDC provider: conformance prep and security review (ADR 005 M6)

_Status: self-review. The official OpenID Foundation conformance suite has **not** been run against this provider; this
page records what it will check, where each item is covered by our own tests, and what is knowingly different._

## Profile targeted
OpenID Connect Basic OP + Config OP (authorization code flow, `response_type=code`). Not targeted: implicit/hybrid,
dynamic registration, request objects (`request`/`request_uri`), `claims` parameter, front/back-channel logout.
Discovery says so (`claims_parameter_supported=false`, `request_parameter_supported=false`, ...).

## Checklist
| Area | Requirement | Where it is tested |
|---|---|---|
| Discovery | Issuer equals the URL discovery is served from; required metadata present; JWKS reachable | `test_oidc_discovery*`, `test_oidc_keys` |
| Authorize | Exact `redirect_uri` match; unknown client/redirect never redirected to; repeated parameters rejected; `state` echoed; `iss` returned (RFC 9207) | `test_oidc_authorize` |
| PKCE | S256 required, `plain` and missing refused | `test_oidc_authorize`, `test_oidc_token` |
| Prompts | `none`, `login`, `consent`, `select_account`; `max_age`; `acr_values` (voluntary) | `test_oidc_prompts_logout` |
| Token | Client auth (Basic / public by id); single-use codes, replay audited; redirect URI re-checked; error format and `Cache-Control: no-store` | `test_oidc_token` |
| ID token | `iss`, `aud`, `sub`, `exp`, `iat`, `auth_time`, `nonce`, `at_hash`, `amr`, `acr`; RS256 with `kid` | `test_oidc_token` |
| UserInfo | Bearer header only; scope-driven claims; `sub` matches the ID token | `test_oidc_token`, `test_oidc_claims` |
| Refresh | Rotation, family reuse detection, idle/absolute limits, revoke | `test_oidc_refresh` |
| Logout | RP-initiated: hint validation, exact post-logout URI, state | `test_oidc_prompts_logout` |
| Browsers | Non-credentialed CORS on token (public clients, own origin only), userinfo, jwks, discovery | `test_oidc_hardening` |

## Known deviations / things a conformance run may flag
- Access tokens are JWTs and cannot be recalled before `exp` (10 min default); `/oauth/revoke` refuses them honestly.
- Refresh tokens survive logout; withdrawing consent or revoking ends them.
- Strict refresh reuse detection with no grace window.
- `client_secret_post` is refused (Basic only); `private_key_jwt` is a later milestone.
- The `acr` claim reports what actually happened rather than what `acr_values` asked for.
- `claims_supported` lists claims we can emit, not per-client sets.

## Hardening added in M6
- `/oauth/authorize` is rate limited per client IP (`RATE_LIMIT_AUTHORIZE_REQUESTS` per `RATE_LIMIT_AUTHORIZE_WINDOW_SECONDS`, default 120/60 s). Redis outage fails open, as for login.
- `python -m backend.cli purge-oidc` deletes expired pending requests (1 h grace), refresh tokens past their family's absolute limit, and old unreferenced codes (1 day grace). Run it from cron or a scheduler; it is idempotent and safe to run concurrently. Rotated refresh tokens and the codes that issued live families are kept on purpose (reuse detection, replay revocation).
- CORS: the cookie-API policy (credentialed, explicit origins) no longer applies to `/oauth/token|userinfo|jwks|revoke` and `/.well-known/*`; they use `oidc/cors.py`: never credentialed; token only for **public** clients and only from one of that client's own redirect-URI origins.

## Security review notes (self-review of the OIDC surface)
Checked and believed sound:
- Open redirect: errors redirect only after client and exact redirect URI are proven; otherwise a 400 page.
- Code/refresh handling: hashed at rest, atomic single use, commits the claim before signing (the `keys.advance()` rollback pitfall is documented in code review notes and covered by replay tests).
- Algorithm confusion: verifiers use an allow-list; the token's `alg` is never trusted; `none`/HS256 tests exist.
- Logout CSRF/forced logout: GET never signs out; the user always confirms; POST needs CSRF + origin.
- Consent screen framing: `frame-ancestors`/`X-Frame-Options` on `/oauth/*` and `/login`.
- Tenancy: all OIDC tables are tenant-owned and scoped fail-closed; purge is the only unscoped path and is explicit (`unscoped`).

Open items (not fixed):
- Rate limiting trusts the direct peer address; behind a proxy configure uvicorn proxy headers.
- No independent review and no official conformance run yet.
- Pending requests are capped only by the per-IP authorize limit, not per client.
- No CORS for `/oauth/revoke` (browser public clients cannot revoke cross-origin).
