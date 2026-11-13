# Ifora

Identity and Access Management Platform built from scratch, not a rebranded solution.

## Overview

Ifora is a modular monolith (FastAPI + Next.js, PostgreSQL as the authoritative store) providing:
- User and Group management, profile attributes and group rules/roles
- Secure authentication: Argon2id passwords, opaque sessions, TOTP and passkeys (WebAuthn)
- Federation: OIDC provider, SAML IdP, Secure Web Authentication (SWA) apps
- Provisioning: inbound SCIM 2.0 server and outbound provisioning to SCIM/REST apps
- Applications, access requests and a security policy
- A recipe engine for workflow automation, with pre-built connectors (GitHub, Jira Cloud, Slack, PagerDuty, Microsoft Entra ID)
- A REST API with admin API tokens, and a SCIM-style list format on every admin collection
- Audit logging for compliance
- Admin and end-user dashboards

Per-feature design notes (ADRs) are in `docs/architecture/`; current status and known gaps are in `docs/project/status.md`.

## Phase 1 Features

- [x] Docker Compose stack
- [x] PostgreSQL data store
- [x] Redis session cache
- [x] One-time administrator bootstrap
- [x] Secure login/logout
- [x] Session management
- [x] Admin RBAC
- [x] User/Group CRUD
- [x] Profile attributes
- [x] System audit events
- [x] Admin dashboard
- [x] End-user dashboard

## Beyond Phase 1

- **Multi-factor authentication**: TOTP with recovery codes and passkeys. With `ADMIN_MFA_REQUIRED` (default `true`) admins must enrol an authenticator app or passkey before the admin area works for them.
- **Federation and apps**: OIDC provider, SAML IdP, SWA, an application catalog with assignments, and user dashboard app tiles.
- **Provisioning**: inbound SCIM server and outbound provisioning to SCIM 2.0 or REST-only apps.
- **Admin API tokens** (`/admin/api-tokens`): bearer tokens for scripts and integrations.
- **Network zones, branding and email templates**: IP/CIDR network zones, tenant branding, and editable invitation and reset emails.
- **Governance**: access requests, group rules, group roles, admin roles, authentication policies and a security policy.
- **Recipe engine** (Workato-style workflow automation, ADR 008/020/021): a studio editor with a resizable step panel, scoped "Handle errors" blocks, else-if chains, lookup tables, callable recipes, formulas, connections, and a send-email step. Details below.
- **Pre-built connectors** (ADR 026): GitHub, Jira Cloud, Slack, PagerDuty and Microsoft Entra ID. Details below.
- **SCIM-style lists** (ADR 025): every admin collection answers `startIndex`, `count`, `sortBy`, `sortOrder` and a SCIM `filter`, and replies `{totalResults, startIndex, itemsPerPage, Resources}`. Sort and filter attributes come from per-collection allow-lists.
- **Outbound email** over SMTP, used by recipes, user invitations and password reset.
- **User naming**: when `PRIMARY_EMAIL_DOMAIN` is set, new users get the username `first.last` (numeric suffix on conflict) and the email `<username>@domain`. The username is immutable (ORM guard plus a database trigger, migration 0050). SCIM ignores `userName` changes instead of failing, and name changes never alter identifiers.
- **User type** is a fixed dropdown: Employee, Contingent Worker, Intern, Service Account, Test Account, Shared Account, Agent Account.

## Recipe engine

Recipes are triggered by an event (user and group lifecycle, sign-in, MFA changes), a schedule, a manual run, a signed webhook (`/hooks/recipes`) or a call from another recipe.

- **Steps**: add/remove group member, set attribute, activate/deactivate user, HTTP request, log, Slack message, send email, lookup-table read/write and connector action. Logic steps: condition (with else-if), stop, for each member, for each item, approval, set variable, wait, throttle, call recipe, return data and scoped "Handle errors" blocks.
- **Data**: datapills from earlier steps, formulas, lookup tables and callable recipes.
- **Safety limits**: caps on steps, runtime, event depth, concurrency and emails per job; an HTTP host allow-list (`RECIPES_HTTP_ALLOWED_HOSTS`); per-recipe rate limits; failure-rate alerts; job retention (`RECIPES_*` settings).
- Jobs run in the `recipes-worker` service.

### Pre-built connectors

Connect an external service once on **Admin > Recipes > Connections**: a catalog lists the connectors, the Connect form is generated from each connector's fields, and **Test** checks the credentials. Then use its actions in the recipe editor. The **Add a step** menu lists each connection's actions grouped under the connection name, and an action's outputs become datapills for later steps.

| Connector | Authentication |
|---|---|
| GitHub | Personal or app token |
| Jira Cloud | Email + API token (basic) |
| Slack | Bot token |
| PagerDuty | API key |
| Microsoft Entra ID | OAuth 2 client credentials |

Security properties:
- Connectors are reviewed YAML definitions in `backend/app/connectors/definitions/`, validated at load time. Admins cannot define arbitrary requests.
- Hosts come only from the definition plus validated connection settings. Placeholders are percent-encoded, redirects are not followed, and the recipe egress policy applies.
- Secrets are Fernet-encrypted with `RECIPE_ENCRYPTION_KEY` and never returned by the API.
- Only read-only or idempotent actions are retried automatically; other actions run at most once.
- Connector calls and connection tests are audited (`CONNECTOR_ACTION_CALLED`, `RECIPE_CONNECTION_TESTED`). Connection management sits under the "automation" admin permission area.

API: `GET /admin/connectors` (catalog), connection create/update under `/admin/connectors`, `POST /admin/recipe-connections/{id}/test`.

## Admin API

Admin collections (users, groups, applications, roles, administrators, access requests, API tokens, recipes and so on) share one list format: `GET /api/v1/admin/<collection>?startIndex=1&count=25&sortBy=<field>&sortOrder=ascending&filter=<SCIM filter>`. `count` defaults to 25 and is capped at 100 (`count=0` returns totals only). Reference docs for every endpoint are at `/docs`. Scripts can authenticate with an admin API token.

## Quick Start

### Prerequisites
- Docker and Docker Compose
- Python 3.12+ (for development)
- Node.js 20+ (for frontend development)

### Configure

1. Copy the example environment file (it is gitignored once copied; never commit `docker/.env`):
```bash
cp docker/.env.example docker/.env
```

2. Fill in the required secrets (`POSTGRES_PASSWORD`, `SECRET_KEY`, `ADMIN_SECRET_KEY`, `MFA_ENCRYPTION_KEY`). The generation commands are in `docker/.env.example`; compose refuses to start without the required ones. Further keys: `OIDC_KEY_ENCRYPTION_KEY` (OIDC signing keys), `SWA_ENCRYPTION_KEY` (SWA apps) and `RECIPE_ENCRYPTION_KEY` (recipe connections, connector credentials and webhooks; empty disables them).

### Start the Platform

```bash
docker compose -f docker/docker-compose.yml up -d --build
```

### Bootstrap Administrator

```bash
curl -X POST http://localhost:8000/api/v1/admin/bootstrap \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@identityforge.local","password":"YourSecurePassword123!","first_name":"System","last_name":"Administrator","secret_key":"<ADMIN_SECRET_KEY>"}'
```

### Access the UI

- Admin Dashboard: http://localhost:3000/admin/dashboard
- User Portal: http://localhost:3000/user/dashboard
- API Docs: http://localhost:8000/docs

## Configuration

Set in `docker/.env` (see `docker/.env.example` for all options):

| Variable | Purpose |
|---|---|
| `ADMIN_MFA_REQUIRED` | Admins must have a passkey or authenticator app (default `true`) |
| `PRIMARY_EMAIL_DOMAIN` | Enables generated usernames and emails for new users; empty keeps manual entry |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM` | Outbound email; leave `SMTP_HOST` empty to disable email |
| `PUBLIC_APP_URL` | Web app address placed in invitation and reset links |
| `RECIPES_EMAIL_ALLOWED_DOMAINS` | Extra external domains the recipe email step may send to (recipients must otherwise be active users) |
| `SESSION_COOKIE_SECURE`, `ENVIRONMENT`, `FRONTEND_TARGET` | Production hardening behind TLS |
| `METRICS_TOKEN` | Enables `GET /metrics` (bearer token) |
| `RECIPE_ENCRYPTION_KEY` | Encrypts recipe connections and connector credentials; empty disables connections and webhooks |
| `RECIPES_HTTP_ALLOWED_HOSTS` | Comma-separated hosts the recipe HTTP step may call; empty allows any public host |
| `RECIPES_ENABLED`, `PROVISIONING_ENABLED`, `GROUP_RULES_ENABLED` | Turn the background workers' processing on or off |

### Production

Run behind a TLS-terminating reverse proxy (not part of this repo) with the production override:

```
docker compose -f docker/docker-compose.yml -f docker/docker-compose.prod.yml --env-file docker/.env up -d --build
```

The override sets `ENVIRONMENT=production`, secure cookies and the compiled frontend, binds every published port to
`127.0.0.1`, and requires `PUBLIC_APP_URL`, `OIDC_ISSUER` (both `https://`), `OIDC_KEY_ENCRYPTION_KEY`,
`FORWARDED_ALLOW_IPS` (your proxy's address) and `CORS_ORIGINS` to be set. Needs Docker Compose 2.24+.

In production the API refuses to start, naming the setting but never its value, when: cookies are not `Secure`;
`SECRET_KEY` or `ADMIN_SECRET_KEY` is short, low-entropy, a placeholder, or the two are equal;
`OIDC_KEY_ENCRYPTION_KEY` is empty or equals `MFA_ENCRYPTION_KEY`; `CORS_ORIGINS` contains `*`; `DEBUG` is on; or
`PUBLIC_APP_URL`/`OIDC_ISSUER` is not `https://`. Development defaults are unchanged.

Client IPs: uvicorn trusts `X-Forwarded-For` only from addresses in `FORWARDED_ALLOW_IPS`. If the header arrives while
that is still the default (`127.0.0.1`), every client looks like the proxy, which breaks throttling, lockout and
IP/CIDR policies; the API logs an error once when it sees this. Confirm real client IPs after your first deploy.

### Demo environment (invite-only)

A second, isolated stack for showing the product to invited people, served at `https://demo.ifora.app` through a
Cloudflare Tunnel, with Cloudflare Access deciding who may connect. It is its own compose project (`ifora-demo`: own
Postgres, Redis and secrets, no published ports), so it shares nothing with the dev/prod stack. `scripts/demo.sh`
runs it:

```
scripts/demo.sh init                      # generate secrets into ~/ifora-demo/.env.demo (outside the repo)
# add CLOUDFLARE_TUNNEL_TOKEN to that file, then:
scripts/demo.sh deploy                    # build and start origin/main, then smoke-test the edge routing
scripts/demo.sh bootstrap-admin <email>   # first administrator; enrol MFA before inviting anyone
```

New features reach the demo by merging to `main` and running `scripts/demo.sh deploy` again; the demo never builds
from a working tree. `scripts/demo.sh reset --yes` wipes the demo data. A Caddy edge sends API, OIDC, SAML and SCIM
paths to the API and everything else to Next.js on one hostname, blocks `/metrics` and `/docs`, and passes
Cloudflare's `CF-Connecting-IP` as the client IP (only the edge address is trusted via `FORWARDED_ALLOW_IPS`).

With `ACCESS_SSO_ENABLED=true` (plus `ACCESS_TEAM_DOMAIN` and `ACCESS_AUD`) a visitor who passed Cloudflare Access is
signed in to Ifora without a second login: the API verifies the Access token itself, creates a non-admin account for a
new invited email, and the first visit goes to `/welcome` (choose a password, optionally add a passkey). Administrators,
accounts with TOTP and passkey-only accounts are never signed in this way; they use their password.

Inviting people: a super administrator uses Users > New user > "Email an invitation" (non-admin; roles are assigned
afterwards on the user's page). With the `ACCESS_ALLOWLIST_*` settings the invited email is also added to the Cloudflare
Access policy, so the emailed link works for them, and it is removed again when the user is deleted. Email goes out over
SMTP; Cloudflare Email Service works with `SMTP_IMPLICIT_TLS=true` on port 465.

## Architecture

### Backend
- **Framework**: FastAPI with Python 3.12
- **Database**: PostgreSQL with SQLAlchemy 2; Alembic migrations in `backend/migrations/`, applied by the container entrypoint
- **Session Store**: Redis + PostgreSQL
- **Password Hashing**: Argon2id
- **Session Tokens**: Cryptographically secure opaque tokens

### Frontend
- **Framework**: Next.js App Router
- **Language**: TypeScript
- **Styling**: Tailwind CSS
- **State**: React Hooks

### Infrastructure
- **Containers**: Docker Compose
- **Database**: PostgreSQL 16
- **Cache**: Redis 7

## Development

### Backend
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt   # includes PyYAML, which loads the connector definitions
uvicorn app.main:app --reload
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

## Testing

### Backend tests
The backend source, including tests, is baked into the Docker image, so rebuild `backend-api` before running them:
```bash
docker compose -f docker/docker-compose.yml up -d --build backend-api
docker exec ifora-api pip install -q -r /app/backend/requirements-dev.txt
docker exec -w /app/backend ifora-api python -m pytest -q
```
Tests use a separate `ifora_test` database.

### Browser tests (Playwright)
Specs live in `frontend/e2e`. They need the stack running and an existing super admin configured in `.env`; some specs are opt-in and need extra variables. See `docs/project/status.md` for the details.
```bash
cd frontend
npx playwright test                                 # everything
npx playwright test e2e/recipe-connectors.spec.ts   # one spec
```
The suite assumes two server modes. Specs that sign in as a freshly created administrator (`admin-roles`, `delegated-resets`, `group-roles`, `nav`, `role-switch`) need the backend started with `ADMIN_MFA_REQUIRED=false`; otherwise that admin is sent to enrol MFA and the spec ends on `/settings#security`. `admin-mfa-policy` needs the default (`true`). Run them in separate passes. Specs sign in as the same admin many times, so run with `--workers=1` when you see "Invalid or expired code" (a TOTP code is single-use).
Coverage includes sign-in and MFA, admin roles, API tokens, OIDC flows, provisioning, access requests and the recipe studio (drag and drop, else-if, loops, formulas, lookup tables, callable recipes, connectors). The connector spec creates and deletes its own `E2E ...` connection and recipe, using a fake token.

## Quality gates (local, no hosted CI)

Gates run on your machine; this repository deliberately has no GitHub Actions workflows (`.github/workflows` must stay empty, and `make no-workflows` enforces it).

```bash
make tools        # which tools you need (ruff, mypy, bandit, pip-audit, gitleaks, semgrep, node)
make check        # every gate; keeps going after a failure and lists FAILED gates at the end
make check-fast   # lint, types on changed files, secret scan, frontend lint/types, no-workflows
make hooks        # install the pre-push hook (runs check-fast) for this checkout
```

Paste the `make check` output into the pull request (see `.github/pull_request_template.md`). Notes:

- Python lint (`ruff`) fails on real errors repo-wide and on unused/undefined names in changed `backend/app` files; `mypy` runs on changed files only. Widening both is tracked as follow-up work.
- `deps-py` and `deps-web` fail on any known advisory. Accept one only by adding `ID | reason | YYYY-MM-DD` (expiry required) to `.security-allowlist` after triage; never to silence a finding you have not read.
- `make test-backend` needs the compose stack up (it reuses the `ifora-api` image, network and env). It runs `scripts/test_backend.sh`, which starts a throwaway container with this checkout mounted, so the running container's baked code is not what is tested. Pass pytest args with `make test-backend PYTEST_ARGS="tests/test_foo.py -x"`. Fixtures create a database on the shared dev Postgres, so never point it at production.
- Server-side branch protection is not available on this repository's GitHub plan (the API returns 403 "Upgrade to GitHub Pro"). As a local substitute, `.githooks/pre-push` refuses any push to `main` or `master` (commits, force-pushes and deletions). It only protects machines that ran `make hooks`, and `git push --no-verify` bypasses it, so this is a guard against mistakes, not an enforced control. Changes reach `main` through a reviewed PR merged on GitHub.

## Backup, restore and rollback

### Backup
```bash
scripts/backup.sh        # ~/ifora-backups/ifora-<UTC>.dump + .manifest, both mode 600
```
The dump is the whole PostgreSQL database in `pg_dump` custom format. The manifest records its sha256, the migration version and row counts (tenants, users, groups, applications, assignments). The script refuses a backup directory inside this checkout: dumps hold password hashes, TOTP secrets and PII, so never commit them, and encrypt them (`age` or `gpg`) before they leave this machine.

Not in the dump, back these up separately and keep them apart from it: everything in `docker/.env` (the Fernet keys `MFA_ENCRYPTION_KEY`, `OIDC_KEY_ENCRYPTION_KEY`, `SWA_ENCRYPTION_KEY` and `RECIPE_ENCRYPTION_KEY` are required to decrypt data in a restored database) and the OpenBao data and unseal material if you use it. Redis holds only sessions and rate-limit counters and is not backed up; users sign in again after a restore.

### Restore
```bash
docker stop ifora-api ifora-recipes-worker             # nothing may write during a restore
scripts/restore.sh ~/ifora-backups/ifora-<stamp>.dump  # target must be empty
scripts/restore.sh <dump> --force                      # replace the existing tables
```
The script verifies the dump against its manifest, refuses a non-empty database without `--force`, restores in one transaction (an interrupted or failing restore leaves the target exactly as it was) and then compares the migration version and row counts (exit 3 if they differ). Start the application afterwards and sign in. To rehearse, point it at a scratch stack: `IFORA_PG_CONTAINER=<scratch-postgres> scripts/restore.sh <dump>`.

### Roll back a release
Images are tagged with the first 12 characters of the commit (`ghcr.io/<owner>/ifora-api:<tag>`). `scripts/deploy.sh` always builds `origin/main`, so use `scripts/ci-deploy.sh` to go back.

1. Before deploying a release that adds a migration, run `scripts/backup.sh`.
2. Pick the commit to return to, and find the migration revision it expects (no database needed):
   `docker run --rm --entrypoint alembic ghcr.io/<owner>/ifora-api:<old-tag> -c backend/alembic.ini heads` (prints for example `0055 (head)`).
3. Compare with the database: `docker exec ifora-api alembic -c backend/alembic.ini current`. If it is the same revision, go to step 5.
4. Otherwise downgrade first, using the newer image that is still running (an older image does not contain the newer migration files and its start-up `alembic upgrade head` fails on the unknown revision):
   `docker stop ifora-recipes-worker && docker exec ifora-api alembic -c backend/alembic.ini downgrade <revision>`.
   A downgrade discards data that only the newer schema holds. If it fails, or that data matters, restore the pre-release backup with `scripts/restore.sh <dump> --force` instead.
5. Deploy the old images: `IMAGE_OWNER=<owner> scripts/ci-deploy.sh deploy local <old-sha>` (`deploy demo <old-sha>` for the demo). A missing image is pulled from GHCR.
6. Verify: `docker exec ifora-api alembic -c backend/alembic.ini current` shows the expected revision, the API health check answers and you can sign in.

Verified on a scratch database: backup, restore (empty target, refusal on a non-empty one, `--force`, tampered and corrupt dumps, an interrupted restore) and `alembic downgrade`/`upgrade` between 0056 and 0055. `scripts/restore-drill.sh` rehearses the whole cycle in throwaway compose projects (`ifora-drill-*`, no host ports, never your real volumes): it populates a database through the API, backs it up, restores into an empty stack, signs in on the restored data, checks that a second restore is refused, and then follows steps 2 to 5 with two real release images (downgrade with the newer image, run the older one). `scripts/ci-deploy.sh` itself is not part of the drill because it only targets the real stacks, so step 5 is the one part not rehearsed. Run it with `IFORA_DRILL_API_IMAGE=<image> IFORA_DRILL_OLD_IMAGE=<older image> scripts/restore-drill.sh`.

## Security

- Passwords hashed with Argon2id
- Session tokens are 256-bit cryptographically secure
- Secure cookie flags (HttpOnly, SameSite) and CSRF protection
- Per-IP login throttling and idle session timeout
- Audit logging for all sensitive operations
- No independent security review yet (see `docs/project/status.md`)

## License

Proprietary - Ifora Development
