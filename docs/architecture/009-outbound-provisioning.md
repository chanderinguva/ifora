# ADR 009: Outbound provisioning (SCIM client and REST gateway)

- Status: **Proposed** (written with the first implementation)
- Date: 2026-11-08
- Inputs: ADR 007 (SCIM server, the inbound direction), ADR 008 (recipe engine: outbound HTTP guard, secret encryption, worker), RFC 7643/7644

## Context
ADR 007 lets an IdP push people into IdentityForge. The other direction is the Okta "SCIM app" model: IdentityForge is the source of truth and **pushes** users and groups to the applications people use. Many applications speak SCIM 2.0; many more only have a REST API. Both must be provisioned from one place, with one lifecycle (create, update, deactivate, delete), one assignment model and one activity view.

## Decisions

### D1. Two adapters behind one interface
`Adapter` (create/find/update/set_active/delete for users, and groups) has two implementations: `ScimAdapter` (RFC 7644: `POST/PUT/PATCH/DELETE /Users`, `GET /Users?filter=userName eq "x"`, `/Groups`, `ServiceProviderConfig` for the connection test) and `RestGateway`, which maps the same canonical SCIM resource into an application's own REST calls described in `rest_config`. The rest of the system never knows which one it talks to. The gateway is deliberately configuration, not code: no scripts run in IdentityForge.

### D2. Entitlement and desired state
A user is *entitled* to an app when assigned directly or through an assigned group. Desired state of (app, user) is "present and active" iff entitled **and** `status = active`. Everything else means deprovision per the app policy: `patch` (set `active=false`, default, Okta's behaviour), `delete`, or `none`. Because lifecycle statuses other than `active` (suspended, locked out, password expired, deprovisioned) all fail the test, status changes reach apps without special cases, and deprovisioning (which also removes group memberships) cascades naturally.

### D3. Reconciliation, not event replay
Every task is idempotent: "make the app match IdentityForge for this user/group". Tasks are queued from the audit hook (`audit.service.record` -> `provisioning.service.on_audit`, same transaction, like the recipe outbox) on user create/update/status/profile changes (including those arriving through inbound SCIM), group membership and rename. Queued tasks for the same target are coalesced. A task computes the canonical resource, hashes it, and calls the app only when the hash differs from the last successful push. Create always looks the user up first (`userName eq`), and a create that answers 409 falls back to linking, so a crash between "created" and "committed" never duplicates an account.

### D4. Mapping
Canonical SCIM User: `userName` (email or username, per app), `externalId` = IdentityForge `public_id`, `active`, `emails`, plus default rules for name, displayName, title, locale, timezone, the enterprise extension (department, costCenter, employeeNumber, organization, division, manager) and phone. Admins add `{target, source}` rules; the same target replaces the default. A source is a field or a `{{template}}` over an **allow-list** (built-in name/email fields and profile-catalog attributes): password data, MFA, roles and tokens cannot be mapped. `userName`, `active`, `externalId`, `id`, `schemas`, `meta`, `groups`, `password` are reserved.

### D5. Security
- Destination: https only, no query/fragment, loopback/private/link-local literals refused at save, and every request goes through the recipe engine's SSRF-safe client (resolve once, require public addresses, connect to the validated IP, **no redirects**, size and time caps). Gateway paths must start with one `/`, stay on the configured host, and cannot contain `..` or a scheme; substituted path values are URL-encoded.
- Credentials: encrypted with `RECIPE_ENCRYPTION_KEY`, never returned by any endpoint, never logged; remote error text is clipped and redacted before it is stored.
- Who: reading and assigning users/groups needs an admin; creating, changing, testing, syncing and deleting an app, and retrying tasks, need a **super admin** (an app decides where user data goes). An app cannot be turned on until a connection test has passed, and changing the URL, auth or secret turns it off again.
- Blast radius: per-tenant task batches, a per-app batch cap per pass, exponential backoff (15 s doubling, cap 10 min, `Retry-After` honoured up to an hour), `PROVISIONING_MAX_ATTEMPTS` (6), then `failed` with an audit event and the link marked `error`. A failed task is retried by a super admin on demand.

### D6. Worker
`provisioning.worker.process_once()` runs inside the recipes worker loop (several workers are safe: `FOR UPDATE SKIP LOCKED` with a lease). Each pass also sweeps *orphans*: links whose user or group row is gone are deprovisioned remotely per policy and forgotten, so deleting a user in IdentityForge deactivates them in the apps without a special delete hook.

### D7. Groups
SCIM apps may also receive the groups assigned to them (`push_groups`): `displayName`, `externalId`, and `members` as the remote ids of provisioned users. Group tasks are re-queued after a member is created or deactivated. The gateway supports groups only if `create_group` is configured.

## Not done
- Importing users from an app, password push, attribute-level "update only on create" flags, per-attribute master priority, OAuth2 client-credentials auth for apps, per-app rate limits beyond the batch cap, and bulk (`/Bulk`) pushes.
- Deleting an app leaves its accounts in the application untouched (they are also forgotten by IdentityForge). Unassign everyone first if they should be deactivated.
- Real-application conformance: tested against an in-memory SCIM server and a fake REST app, not against Okta-certified or vendor sandboxes.
