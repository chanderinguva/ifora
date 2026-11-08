# IdentityForge Project Status

_Last updated: 2026-11-05_

## Phase 1 scope vs. reality

| Item | Status | Notes |
|---|---|---|
| Docker Compose stack | Done | postgres, redis, backend-api, frontend (health-checked, named volumes) |
| Database migrations | Done | Alembic (`backend/migrations/`), applied by the container entrypoint; legacy databases are adopted at baseline 0001. A test fails if models and migrations drift. |
| Admin bootstrap & login | Done | `POST /api/v1/admin/bootstrap` (secret key, once) |
| End-user login & logout | Done | Session cookie + CSRF, see ADR 003 |
| Session management | Done | Hashed opaque tokens, revocation, "my sessions" |
| Admin RBAC | Done | admin / super admin, deny-by-default |
| User CRUD | Done | API + admin UI (list, search, filter, create, edit, deactivate, reset password, delete) |
| Group CRUD + membership | Done | API + admin UI |
| Profile attributes | Done | Admin-managed + user-editable allow-list |
| System audit events | Done | Recorded in the same transaction; viewer with filter |
| Admin dashboard | Done | Real counts from the database, recent activity |
| User dashboard | Done | Profile, groups, change password, active sessions |
| Browser & API tests | Done | 879 API integration tests (real Postgres test DB) + 28 Playwright browser tests (2 opt-in: demo app, admin MFA policy) (the policy spec needs a throwaway admin, see below) (incl. a Chrome virtual authenticator) |
| Security review | **Partial** | Self-review recorded in ADR 003; no independent review yet |

## Hardening done after Phase 1
- TOTP multi-factor authentication with recovery codes (ADR 003).
- Passkeys (WebAuthn): usernameless sign-in, optional "require a passkey" policy, admin reset (ADR 003).
- Admin MFA policy (`ADMIN_MFA_REQUIRED`, on by default) with one-time enrolment codes for first enrolment (ADR 003).
- Navigation shell: grouped, collapsible sidebar, breadcrumbs, mobile drawer, skip link (ADR 004).
- Role view: admins can work as a normal user per session; switching back needs the password (ADR 003).
- Brand identity (forge-fold mark, Lora wordmark, theme-aware logo, favicon/app icons; `docs/brand/guidelines.md`).
- Dark theme (Light / System / Dark switch in the header and on the login page).
- Operator recovery CLI for lost factors (`python -m backend.cli reset-factors <email>`, ADR 003).
- Account settings page and header user menu for all roles (MFA/passkey enrolment, password, sessions).
- Per-IP login throttling and bootstrap-key throttling (Redis), idle session timeout (30 min).
- Secrets live in gitignored `docker/.env`; compose refuses to start without them. Postgres/Redis bind to 127.0.0.1 only.

## Not done / known gaps
- `SESSION_COOKIE_SECURE` is off (plain HTTP in dev); turn it on behind TLS. Behind a reverse proxy, configure uvicorn `--proxy-headers`/`--forwarded-allow-ips` so rate limiting sees real client IPs.
- The default compose stack still runs `next dev`; a production target exists (`FRONTEND_TARGET=prod`, compiled `next start`, non-root, built and smoke-tested with `/login` returning 200 but not load-tested).
- No independent security review yet.

## Running
```bash
cp docker/.env.example docker/.env   # then fill in the three secrets (generation commands inside)
docker compose -f docker/docker-compose.yml up -d --build
# UI  http://localhost:3000    API docs  http://localhost:8000/docs
```

Bootstrap the first administrator (key = `ADMIN_SECRET_KEY` from the compose file):
```bash
curl -X POST http://localhost:8000/api/v1/admin/bootstrap -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"<12+ chars, mixed case, digit>","first_name":"System","last_name":"Administrator","secret_key":"<ADMIN_SECRET_KEY>"}'
```

## Tests
```bash
# API (creates/uses database identityforge_test; the dev database is untouched)
docker exec identityforge-api pip install -q -r /app/backend/requirements-dev.txt
docker exec -w /app/backend identityforge-api python -m pytest -q

# Browser (system Chrome; needs the stack running; creates and deletes its own user/group)
cd frontend && set -a && . ../.env && set +a && npx playwright test
```
`.env` must contain `ADMIN_EMAIL` and `ADMIN_PASSWORD` of an existing super admin. If that admin has enrolled an authenticator app (as the policy requires), also set `ADMIN_TOTP_SECRET` (its base32 secret); without a second factor and with the policy on, the admin cannot reach the admin area, so run the suite with `ADMIN_MFA_REQUIRED=false` on the backend instead. `role-switch.spec.ts` needs `E2E_ROLE_ADMIN_EMAIL`/`E2E_ROLE_ADMIN_PASSWORD` for a throwaway admin and a backend with `ADMIN_MFA_REQUIRED=false`. `admin-mfa-policy.spec.ts` needs `E2E_POLICY_ADMIN_EMAIL`, `E2E_POLICY_ADMIN_PASSWORD` and `E2E_ENROLMENT_CODE` for a throwaway admin with no factor (never the real admin); it is skipped otherwise.

## Account lifecycle and recovery (added later)
- Okta-style statuses; deactivation removes every group membership (ADR 006 addendum).
- Outbound provisioning (ADR 009): push users and groups to SCIM 2.0 apps, or to REST-only apps through a configurable gateway; assignments (user or group), entitlement-driven deactivate/delete, retries with backoff, orphan sweep, activity view. Verified against an in-memory SCIM server and a fake REST app, not against real vendor apps.
- Invitations and email password reset (`/auth/forgot-password`, `/auth/reset-password`, admin `send-invite` / `send-reset`); needs `SMTP_*` and `PUBLIC_APP_URL`. Tokens are single use, hashed, 30 min (reset) / 72 h (invite), carried in the URL fragment. Unverified against a real mail server: tests use an in-process mailer.
- Forced password change: an admin reset with `require_change` sets `password_expired`; sign-in then returns `password_change_required` and the user proves the old password (`/auth/change-expired-password`).
