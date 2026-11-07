# ADR 008: Recipe engine (identity workflow automation)

- Status: **Proposed** (implemented as an MVP vertical slice on branch `feature-recipe-engine`; owner review requested on the starred decisions)
- Date: 2026-11-06
- Inputs: ADR 005 (tenancy, key handling), ADR 006 (structured conditions, "no eval", self-editable attributes are untrusted), `backend/app/audit/`

## Context
Admins want Workato / Okta Workflows style automation for identity: "when X happens, do A, then if B do C". A **recipe** is one trigger plus an ordered list of steps (actions, conditions/branches). Data flows between steps as **datapills** (`{{trigger.user.email}}`). A durable worker runs recipes with retries and keeps a job history.

## Research (how others model it)
Confidence: H = read in the vendor documentation during this session, M = recalled from earlier knowledge, not re-read.

| Claim | Source | Conf. |
|---|---|---|
| Workato: a recipe is one trigger + steps; each execution is a **job**; the recipe's *Jobs* tab is the history; a failed job can be re-run from the job report, which re-processes the whole trigger event and may duplicate records | docs.workato.com error-handling, rerun-job | H |
| Workato error handling is explicit: a *Handle errors* step has a **Monitor** block and an **On error** block; retries are off by default, configurable up to 3 with a 1-10 s delay; error type/message/retry count are exposed as datapills; "Job failed" / "Recipe stopped" system triggers allow cross-recipe alerting | docs.workato.com error-handling | H |
| Okta Workflows: `If Error` card (Try / If Error blocks); execution history stores per-card input/output **only if "save flow data" is enabled**, retained 30 days; error notification is typically a helper flow | help.okta.com execution-history, support.okta.com | H |
| Entra Lifecycle Workflows: a workflow = **trigger** (time-based attribute, group membership change, on-demand) + **scope** (rule selecting users) + ordered **tasks**; history can be viewed by user, run or task | learn.microsoft.com lifecycle-workflow-execution-conditions | H (failed-task retry semantics not found: unknown) |
| Workato/Okta connections hold credentials centrally, referenced by id from steps, never shown after creation | general product knowledge | M |
| Okta Workflows does not execute user code in the base card set; Workato offers a Ruby/JS "formula" mode | general product knowledge | M |

What we take: Workato's job + per-step history, per-step retry settings and "rerun is at-least-once" honesty; Okta's *opt-in data retention* idea (we redact by key name and never store connection secrets); Entra's trigger + scope split (our trigger `filter` conditions) and the user/run/task views (job history). What we deliberately do **not** take: formula/code steps (the MVP has no expression language at all) and arbitrary connectors.

## Decisions

### D1 Triggers and the event envelope (*)
Triggers: `user.created`, `user.activated`, `user.deactivated`, `user.updated`, `user.attribute_changed` (config: one admin-managed attribute), `group.member_added`, `group.member_removed` (config: optional group), `login.failed` (config: minimum consecutive failures), `schedule` (interval in minutes, 5-1440), `manual`, `webhook` (per-recipe HMAC secret). Every trigger additionally accepts a structured `filter` (same condition model as steps).

Event envelope (JSON, stored in `recipe_outbox.payload`):
```
{ "type": "group.member_added", "version": 1, "occurred_at": "...Z",
  "actor": {"type": "user"|"recipe"|null, "id": "..."},
  "data": {"user": {id,email,username,first_name,last_name,status,attributes{}}, "group": {id,name}, ...} }
```
The envelope is a **snapshot at emit time** so a recipe sees the state that caused the event, not whatever the row looks like when the worker gets to it. The outbox row also carries `depth` and `origin_recipe_id` (D5).

**Reliable emission (transactional outbox).** Events are emitted by `audit.service.record()`, which every state change already calls inside the request's transaction (callers commit). `record()` gained one additive call to `recipes.events.emit_from_audit()` that `db.add()`s an outbox row. Because it lives in the same session/transaction as the change and its audit row: rollback emits nothing (no phantom events) and commit always emits (no lost events). Two direct emitters (not covered by `record()`): `user.attribute_changed` from the admin user update route and `login.failed` (the login path writes its audit row itself). To avoid unbounded growth the emitter only writes a row when at least one **enabled, published** recipe listens for that event type in the tenant; dispatched rows older than 7 days are pruned.

### D2 Steps (*)
Actions: `add_to_group`, `remove_from_group`, `set_attribute` (admin-managed catalog attributes only), `activate_user`, `deactivate_user`, `http_request` (SSRF-safe, optional connection), `log`. Control flow: `condition` (structured, `then`/`else` branches, nestable to depth 3), `stop` (success or failed outcome). At most 30 steps per recipe definition.

Datapills: `{{path}}` only. No filters, no expressions, no method calls. The resolver walks **plain JSON dicts/lists** from an allow-listed root (`trigger`, `steps.<id>.output`, `recipe`, `job`); each segment must match `[A-Za-z0-9_-]+` and may not start with `_`; there is no `getattr`, so `__class__` style traversal cannot exist. Anything else containing `{{` is rejected at save time. A string that is exactly one pill keeps the raw JSON value (so ids stay integers).

**Taint rule (*)**: a user can edit their own first/last name and "user-editable" profile attributes. Those values are untrusted. They may **not** be used in condition operands, trigger filters or the value of `set_attribute` (otherwise a user could edit their way into a group or launder a value into an admin-managed attribute that group rules read - the ADR 006 problem, one level up). Enforced at save time and again at run time against the current catalog. They may be used in `http_request` and `log`.

### D3 Execution model (*)
`outbox -> dispatcher -> job queue -> worker`, all in Postgres, run by `python -m backend.cli recipes-worker` (loop around `engine.process_once()`), safe to run several copies. `process_once(now)` is a plain function so tests need no sleeps.

1. **Dispatch**: `SELECT ... FROM recipe_outbox WHERE dispatched_at IS NULL FOR UPDATE SKIP LOCKED`; for each event and each matching enabled recipe insert a job with idempotency key `evt:<event_id>`; unique `(recipe_id, idempotency_key)` makes redelivery a no-op. Mark dispatched in the same transaction.
2. **Schedule**: due `schedule` recipes get a job keyed `sched:<slot>` (slot = floor(epoch / interval)), so two workers or a restarted worker cannot double-fire a slot; missed slots collapse into the current one (no backfill storm).
3. **Run**: claim due jobs with `FOR UPDATE SKIP LOCKED`, set status `running` with a lease (`locked_until`); a crashed worker's job is re-claimed when the lease expires. Each step executes in **one transaction together with its effects, its audit rows, its outbox emissions and the job's progress** (`pc`), so DB actions are exactly-once per progress commit. `http_request` is inherently at-least-once (crash between response and commit re-sends); every request carries `Idempotency-Key: <job>-<step>`.
4. **Retries**: per step `max_attempts` (1-5, default 3), exponential backoff `base * 2^(n-1)` capped at 300 s, only for retryable failures (network error, timeout, 429, 5xx, unexpected internal error). Validation-type failures (bad target, 4xx, SSRF block) fail immediately. `on_error: continue` lets a step fail without failing the job. Every attempt is a history row.
5. **Limits**: max 500 executed steps per job (loop iterations count), max runtime 900 s from creation, per-recipe concurrency 5 running jobs, HTTP timeout 10 s, response cap 1 MB, webhook body cap 64 KB.
6. **Why not Celery/Kafka/RQ**: we already need Postgres for the authoritative state; the outbox must be in the same transaction as the change, which no external broker can give us; volume is admin-driven, not streaming. `SKIP LOCKED` queues are the boring, well-understood choice. Revisit if sustained throughput exceeds what one Postgres queue handles (backlog R5).
7. **Why a separate worker command, not the API lifespan**: the API process should not run long outbound calls; a separate process can be restarted, scaled and kill-switched independently. A compose service is a one-line addition (not done here: shared containers must not be touched).

### D4 Dry run, versioning, kill switches
- **Versioning (*)**: a recipe has a mutable `draft`. *Publish* validates and inserts an **immutable** `recipe_versions` row (no update/delete route; the job copies the definition, so even a hypothetical edit of a version cannot change a running job). Triggers use the published version only; jobs record `version`. Draft edits never affect production runs.
- **Test / dry run** runs the **draft** synchronously in `dry_run` mode: conditions are really evaluated, templates really resolved, targets (group, user, attribute rules) really validated, but nothing is written, no HTTP request is sent, and the job history shows what *would* have happened.
- **Kill switches**: global `RECIPES_ENABLED` (off: API 404, no events emitted, worker idle; queued jobs stay queued) and per-recipe enable/disable (disabled: no new jobs, queued jobs are cancelled at claim time). Enabling needs a published version.

### D5 Loop protection (*)
Every outbox event carries `depth` and `origin_recipe_id`. While a step runs, the session carries `recipe_origin = {recipe_id, job_id, depth}`; any event emitted in that window gets `origin_recipe_id = recipe_id`, `depth = job.depth + 1`. Rules: (1) **a recipe never receives an event its own steps caused**; (2) **events deeper than 3 are not dispatched at all** (bounds A -> B -> A ping-pong and A -> B -> C chains); (3) 50-step and 900-s caps bound a single job. Dropped events are marked dispatched with no job.

### D6 Security model (*)
Threat model (actor -> asset -> mitigation):

| # | Threat | Mitigation |
|---|---|---|
| T1 | Recipe author uses the HTTP step to reach internal services / cloud metadata (SSRF) | Scheme allow-list (http/https), no userinfo, port allow-list (80, 443, 8080, 8443). The hostname is resolved **once**; every resulting address must be globally routable (`ipaddress.is_global`, plus explicit blocks for IPv4-mapped IPv6, NAT64 `64:ff9b::/96`, 6to4 `2002::/16`, Teredo `2001::/32`); the TCP connection is then made **to the validated IP** (URL rewritten, `Host` header and TLS SNI/verification kept on the original name), so a DNS answer cannot change between check and use (rebinding). Redirects are **not followed** (3xx is returned as a result); `trust_env=False` (no proxy env). Response streamed with a byte cap; total timeout. Optional `RECIPES_HTTP_ALLOWED_HOSTS`. Relaxing the policy (loopback in tests) is possible only by injecting a policy object in code, never via settings. |
| T2 | Credential theft through connections | Secrets Fernet-encrypted with `RECIPE_ENCRYPTION_KEY` (a third, separate key; must differ from `MFA_ENCRYPTION_KEY` and `OIDC_KEY_ENCRYPTION_KEY`; empty = connections and webhook triggers disabled). The API never returns secrets (only `has_secret`). A connection is **bound to one host**: the step URL host must equal it, so a recipe cannot send the token elsewhere. Secrets are injected as a header at the last moment, never put into step input; keys named like `authorization`/`token`/`secret`/`password`/`api_key`/`cookie` are redacted in history and API output; any echo of the secret in a response is scrubbed before storage. Secrets are never logged. |
| T3 | Privilege escalation via recipes | **Admin is `users.is_admin` / `is_super_admin` only**; `require_admin` never consults groups (verified in `auth/deps.py`), so adding a user to any group cannot make them admin, and the test suite asserts it. No step can set admin flags or call arbitrary admin API routes; the action set is fixed and each executor validates its target. Recipes cannot activate/deactivate administrator accounts, cannot touch system groups, cannot remove rule-managed memberships, can only set admin-managed attributes. Residual: groups feed the OIDC `groups` claim, so a recipe can grant access in *relying parties*; this is why recipe management is admin-only, targets are fixed ids in the definition, and every change is audited. |
| T4 | Untrusted user data steers a recipe | Taint rule (D2). |
| T5 | Unauthenticated callers trigger runs | Webhook: HMAC-SHA256 over `timestamp.body` with the per-recipe secret, `hmac.compare_digest`, 300 s window, replay of the same signature maps to the same idempotency key (no second job), 64 KB cap, per-IP failure throttling, uniform 401 for bad signature. Unknown/disabled recipe is a 404 (public ids are 128-bit random). |
| T6 | Cross-tenant access | All recipe tables are `TenantOwned` (ORM-scoped, fail closed); the worker opens one tenant-bound session per tenant; there is no unscoped query on recipe data. |
| T7 | Audit gaps / repudiation | Recipe and connection CRUD, publish, enable/disable, test run, manual run, webhook intake and every job outcome are audited; each action step writes the same audit event a manual change would, with actor type `recipe` (`actor_id = recipe:<id>`) and `via_recipe`/`job_id` metadata. |
| T8 | Resource exhaustion | Limits in D3; outbox only written when a listener exists; max 100 recipes, 30 steps, 64 KB definitions. |
| T9 | Template/expression injection | There is no evaluator: pills are dictionary lookups (D2). |
| T10 | Stored secrets in history | Job step input/output is passed through the redactor before storage; webhook payloads are redacted by key name on API output. |

Who may do what: only a signed-in **admin in admin view** (same `require_admin` as the rest of `/admin`) may create, edit, publish, enable, run or view recipes, connections and jobs. Non-super admins are allowed on purpose because recipe actions are a subset of what any admin can already do by hand; admin-targeting actions are impossible for everyone.

### D7 Audit
New actions: `RECIPE_CREATED/UPDATED/DELETED/PUBLISHED/ENABLED/DISABLED`, `RECIPE_TEST_RUN`, `RECIPE_MANUAL_RUN`, `RECIPE_WEBHOOK_SECRET_ROTATED`, `RECIPE_WEBHOOK_RECEIVED`, `RECIPE_JOB_SUCCEEDED/FAILED/CANCELLED`, `RECIPE_CONNECTION_CREATED/UPDATED/DELETED`.

## API (all under `/api/v1`, admin only unless noted)
`GET /admin/recipes/status|meta`, `GET|POST /admin/recipes`, `GET|PUT|DELETE /admin/recipes/{id}`, `POST .../{id}/publish|enable|disable|test|run|webhook-secret`, `GET .../{id}/versions[/{n}]`, `GET /admin/recipes/jobs[/{id}]`, `GET|POST /admin/recipe-connections`, `PUT|DELETE /admin/recipe-connections/{id}`, and **public** `POST /hooks/recipes/{public_id}` (signature auth).

## Known gaps and residual risks
- R1 Outbound requests can still go to *any public* host unless `RECIPES_HTTP_ALLOWED_HOSTS` is set (data exfiltration by an admin-authored recipe; the admin already holds the data, so this is an insider risk, not a new boundary).
- R2 HTTP step side effects are at-least-once; remote systems must honour `Idempotency-Key`.
- R3 Recipe version immutability is enforced by the application (no write path), not by a database trigger.
- R4 Webhook intake counts failures per IP using the existing Redis limiter, which fails open if Redis is down.
- R5 Single-queue Postgres throughput; no priority lanes; no per-tenant fairness yet.
- R6 `FOR UPDATE` leases rely on worker clocks being roughly in sync with the DB clock (we use the worker clock for `next_run_at`).
- R7 Group-membership changes made by recipes can grant access in relying parties through OIDC `groups` (see T3).
- R8 The connection host binding compares host strings; a connection to a host whose DNS later points elsewhere is still protected by the SSRF check, not by the binding.
- R9 Retry backoff has no jitter.

## Backlog

| ID | Milestone | Item |
|---|---|---|
| R-M1 | **done (this PR)** | Outbox + hooks, dispatcher/worker, 7 actions, conditions, datapills, SSRF-safe HTTP, connections, versions, dry run, job history, builder UI |
| R-M2 | **done** | Re-run (`POST /admin/recipes/jobs/{id}/rerun`: new job, same version and trigger, at-least-once, audited), cancel (queued: immediately; running: stops before its next step), `on_error` handler steps (see below), job retention (`RECIPES_JOB_RETENTION_DAYS`, default 30, 0 = keep; step history cascades), worker as compose service `recipes-worker` with a heartbeat file health check and a Redis heartbeat that the Jobs page and `/admin/recipes/status` show. Migration 0021 |
| R-M3 | **done** | New triggers: user deleted, group created/deleted, login succeeded, attribute changed from/to filter. `for_each_member` (one level, max 100 members, `loop.*` datapills, user-editable loop fields tainted). `approval` step: job goes `waiting`, an administrator approves/denies (`POST /admin/recipes/jobs/{id}/approve|deny`, audited) or it times out (1-168 h) into the else branch; waiting time is excluded from the runtime cap. Not done: session events other than login |
| R-M4 | **done** | `send_slack` (incoming-webhook connection; `& < >` escaped so user text cannot @-mention or inject links; the webhook URL is the encrypted secret and is host-pinned to hooks.slack.com), `send_email` (SMTP via `SMTP_*`; one recipient that must be an active user or in `RECIPES_EMAIL_ALLOWED_DOMAINS`; subject/recipient CR/LF rejected; `RECIPES_MAX_EMAILS_PER_JOB`; at-least-once, so a retry after an ambiguous failure can duplicate), OAuth2 **client-credentials** connections (token fetched through the same egress guard, cached per process until shortly before expiry, dropped when the connection is edited), per-connection `allowed_paths` prefixes (traversal and encoded dots/slashes refused). Not done: OAuth2 authorization-code/refresh flows (need a browser consent step), per-recipient email templates, delivery receipts |
| R-M5 | **done** | Owners and editors per recipe: owner/super admin publish, enable, run, delete, rotate the webhook secret and control jobs (rerun/cancel/approve/deny); editors change the draft and dry-run it; every other admin is read-only (`PUT /admin/recipes/{id}/settings`, audited). A Postgres trigger makes `recipe_versions` immutable (UPDATE always refused; DELETE only when the recipe itself is gone). Per-recipe `rate_limit_per_hour` (server default `RECIPES_DEFAULT_RATE_PER_HOUR`, 0 = unlimited) caps automatic triggers; dropped events are counted, one audit line per burst, webhooks get 429; manual runs and re-runs are exempt. `GET /admin/recipes/metrics` (per recipe: counts, failure rate, p50/p95, queue depth) and a failure-rate alert (`RECIPES_ALERT_*`: audit event + warning log, once per window, shown on the Health page and recipe list). Alerts are not pushed to email/Slack by themselves; a recipe with a webhook or audit-log consumer can do that. Not done: role-scoped *connection* permissions (any admin can still use any connection), Prometheus exposition |
| R-M6 | | Visual graph editor, import/export of definitions, recipe templates |


## R-M2 notes: error handler
`definition.on_error` is an optional list of steps (same grammar). When a step fails for good (retries used up, not `on_error: continue`), the job switches to the handler steps with `{{error.message}}` and `{{error.step_id}}` available, then ends as **failed** with the original error (a handled error is still a failure in the history; there is no "swallow the error" mode). Rules: handler steps see the trigger, recipe, job and error, not the outputs of main steps (which of them ran is unknown); step ids are unique across both lists; `error.*` cannot be used in conditions or in account-changing steps (the text can carry remote-system or user-controlled content), only in log/HTTP steps. A deliberate `stop` step does not invoke the handler. A failing handler step ends the job and is reported. Dry runs execute the handler too. Re-run is explicit and may repeat effects the first run already had.
