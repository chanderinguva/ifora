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
| Browser & API tests | Done | 116 API integration tests (real Postgres test DB) + 7 Playwright browser tests (incl. a Chrome virtual authenticator) |
| Security review | **Partial** | Self-review recorded in ADR 003; no independent review yet |

## Hardening done after Phase 1
- TOTP multi-factor authentication with recovery codes (ADR 003).
- Passkeys (WebAuthn): usernameless sign-in, optional "require a passkey" policy, admin reset (ADR 003).
- Operator recovery CLI for lost factors (`python -m backend.cli reset-factors <email>`, ADR 003).
- Account settings page and header user menu for all roles (MFA/passkey enrolment, password, sessions).
- Per-IP login throttling and bootstrap-key throttling (Redis), idle session timeout (30 min).
- Secrets live in gitignored `docker/.env`; compose refuses to start without them. Postgres/Redis bind to 127.0.0.1 only.

## Not done / known gaps
- MFA policy (require for admins), email-based password reset.
- `SESSION_COOKIE_SECURE` is off (plain HTTP in dev); turn it on behind TLS. Behind a reverse proxy, configure uvicorn `--proxy-headers`/`--forwarded-allow-ips` so rate limiting sees real client IPs.
- Frontend runs `next dev` inside Docker (development mode).
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
`.env` must contain `ADMIN_EMAIL` and `ADMIN_PASSWORD` of an existing super admin.
