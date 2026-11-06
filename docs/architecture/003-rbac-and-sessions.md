# ADR 003: RBAC and session-cookie authentication

## Status
Accepted

## Sessions
- Login issues a random 256-bit opaque token in an `HttpOnly`, `SameSite=Lax` cookie (`Secure` when `SESSION_COOKIE_SECURE=true`). Only the SHA-256 of the token is stored (`sessions.token`).
- Sessions are server-side revocable. Logout, password change/reset, deactivation and role change revoke sessions.
- CSRF: every non-GET request on a session needs `X-CSRF-Token` = HMAC(`SECRET_KEY`, session token). The token is returned by `POST /login` and `GET /me`; the SPA keeps it in memory only. Unsafe requests also fail when `Origin` is present and not in `CORS_ORIGINS` (this also covers login CSRF).
- Failed login, unknown user, locked or inactive account all return the same `401 Invalid credentials`; unknown/locked paths run a dummy Argon2 verify to equalise timing.

## Roles (deny by default)
| Role | Can |
|---|---|
| Anonymous | `login`, `admin/bootstrap` (secret key, once) |
| User | `/me/*`: own profile (allow-listed attributes only), own password, own sessions |
| Admin | All `/admin/*` user, group, audit, stats endpoints on non-admin users |
| Super admin | Additionally: create/demote admins, modify admins. Cannot be modified, deactivated or deleted through the API |

Every `/admin/*` route depends on `require_admin`; there is no route that is open by omission.
Rules enforced server-side: no self-delete/self-deactivate, mass-assignment ignored (`is_super_admin`, `password_hash` are not accepted), users cannot edit admin-managed attributes (e.g. `department`) because attributes may later drive authorization.

## Abuse controls
- Per-account lockout (5 failures, 15 min) plus per-IP throttle of failed logins (10 / 5 min, Redis, HTTP 429 + Retry-After) and of bootstrap-key guesses. A successful login does not reset the IP counter, so a valid account cannot be used to reset guessing against others. The limiter fails open if Redis is down (logged).
- Sessions: 8 h absolute lifetime and 30 min idle timeout.

## Multi-factor authentication (TOTP)
- RFC 6238 TOTP (SHA-1, 6 digits, 30 s, ±1 step drift) via `pyotp`; works with standard authenticator apps.
- Secrets are Fernet-encrypted at rest with `MFA_ENCRYPTION_KEY` (separate from `SECRET_KEY`). Losing or rotating this key makes enrolled secrets undecryptable (users must re-enrol, admins can reset).
- Login becomes two steps. A correct password returns a short-lived challenge (5 min, 5 attempts, hashed at rest) and **no session**; `POST /login/mfa` exchanges challenge + code for the session cookie. MFA failures count toward the IP throttle and the account lockout, and each successful TOTP step can be used only once (atomic conditional UPDATE).
- 10 single-use recovery codes (60 bits each), stored as SHA-256 hashes, shown once. Regeneration invalidates the old set.
- Enrol / disable / regenerate need the current password; disable and regenerate also need a valid code. Enabling or disabling revokes the user's other sessions.
- Admins can reset a user's MFA (lost device); same target protections as other admin actions, sessions revoked, audited.

## Passkeys (WebAuthn, phishing-resistant)
- `py_webauthn` 3.x. Registration requires a discoverable credential and user verification; sign-in is usernameless (`POST /login/passkey/options` then `/verify`). RP ID and allowed origins are configuration (`WEBAUTHN_RP_ID`, `WEBAUTHN_ORIGINS`).
- Ceremonies are single-use, DB-stored challenges (5 min). A signature-counter rollback is rejected and audited. Each user has a random `webauthn_handle` (never the email or id).
- A verified passkey (user verification) is multi-factor on its own, so TOTP is skipped on passkey sign-in.
- Add / remove / policy changes need the current password. Already-registered devices are excluded from registration.
- Policy "require a passkey" needs at least 2 passkeys, revokes other sessions, and makes password and TOTP login return 403 (only after the password is correct, to avoid leaking account state).
- Admin "reset sign-in factors" removes TOTP, passkeys and the policy (lost devices), revokes sessions, and is audited.
- Every role (user, admin, super admin) enrols from **Account settings** (header user menu), the same self-service API.

## Operator recovery (lost every factor)
Other admins cannot reset a super admin, so recovery is an operator action with shell access to the deployment (that access is the trust boundary):
`docker exec -w /app identityforge-api python -m backend.cli reset-factors <email>` (`--yes` skips the prompt).
It removes TOTP, recovery codes and passkeys, lifts the passkey-required policy, clears any lockout, ends all sessions and leaves the password untouched. Each run is audited as `MFA_RESET` with `via: cli` and no actor. It shares `mfa_service.reset_all_factors` with the admin API.

## Known gaps (not yet implemented)
- No policy forcing admins to enrol; no password reset by email.
- Client IP is the direct peer address; configure the ASGI server's proxy-header handling when deployed behind a proxy.
