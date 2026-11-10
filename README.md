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
Tests use a separate `identityforge_test` database.

### Browser tests (Playwright)
Specs live in `frontend/e2e`. They need the stack running and an existing super admin configured in `.env`; some specs are opt-in and need extra variables. See `docs/project/status.md` for the details.
```bash
cd frontend
npx playwright test                                 # everything
npx playwright test e2e/recipe-connectors.spec.ts   # one spec
```
The suite assumes two server modes. Specs that sign in as a freshly created administrator (`admin-roles`, `delegated-resets`, `group-roles`, `nav`, `role-switch`) need the backend started with `ADMIN_MFA_REQUIRED=false`; otherwise that admin is sent to enrol MFA and the spec ends on `/settings#security`. `admin-mfa-policy` needs the default (`true`). Run them in separate passes. Specs sign in as the same admin many times, so run with `--workers=1` when you see "Invalid or expired code" (a TOTP code is single-use).
Coverage includes sign-in and MFA, admin roles, API tokens, OIDC flows, provisioning, access requests and the recipe studio (drag and drop, else-if, loops, formulas, lookup tables, callable recipes, connectors). The connector spec creates and deletes its own `E2E ...` connection and recipe, using a fake token.

## Security

- Passwords hashed with Argon2id
- Session tokens are 256-bit cryptographically secure
- Secure cookie flags (HttpOnly, SameSite) and CSRF protection
- Per-IP login throttling and idle session timeout
- Audit logging for all sensitive operations
- No independent security review yet (see `docs/project/status.md`)

## License

Proprietary - Ifora Development
