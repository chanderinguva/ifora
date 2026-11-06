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

## Known gaps (not yet implemented)
- No MFA / password reset by email.
- Client IP is the direct peer address; configure the ASGI server's proxy-header handling when deployed behind a proxy.
