# ADR 022: Workato recipe-engine parity (scope, architecture, how we track it)

## Status
Accepted. Builds on ADR 008 (recipe engine), 020 (editor) and 021 (advanced steps). The registry is `docs/workato-parity/features.yaml`; the generated progress report is `docs/workato-parity/STATUS.md` (`python3 docs/workato-parity/report.py` validates the registry and rewrites it).

## Context and problem statement
The owner wants recipe authoring and execution that matches what Workato recipes can do, with the same interaction model, backed by a real engine (no mock steps, no UI-only features). Workato is proprietary: only its public documentation is a specification, and much of it could not be read for this ADR (several pages returned 404 or carried no detail). The risk is claiming parity we cannot show, or copying behaviour we guessed.

## Decision drivers
1. Real execution: every step, pill and formula resolves against the real engine; the editor and the runtime share one validator.
2. Security first: an identity platform must not let a recipe turn user-editable data into account changes (the taint rule of ADR 008 stays the invariant for every new feature).
3. Honest tracking: a feature is `verified` only when its acceptance criteria are covered by passing automated tests; unread documentation is recorded as `not_researched`, never filled in.
4. Small, reviewable increments, each with tests, one pull request per feature group.

## Decision
Keep the modular monolith and the existing engine; add Workato-style capabilities as engine features behind the same definition schema, and track them in a machine-readable registry. We do **not** build a second engine, a node-graph canvas, or a Ruby runtime. Compatibility is of *behaviour documented by Workato*, not of its file formats, formula language or SDK.

## Alternatives considered
- **Embed or wrap an open-source workflow engine** (n8n-style graph): rejected, different interaction model and a second authorization and audit surface.
- **Implement Workato's Ruby formula mode and Ruby Connector SDK**: rejected for now. It would need a sandboxed Ruby runtime (ADR 021 section 4 is still undecided) and the formula allow-list is not fully public. Our closed formula language (ADR 021 section 1) gives the same capability with a smaller attack surface; formulas are not portable to Workato.
- **Declare parity from a feature checklist alone**: rejected; the registry requires files and tests and `report.py` fails on a `verified` entry with no tests or a path that does not exist.

## Architecture (what exists, what is planned)
- **Recipe editor**: one vertical flow, step cards, right-hand panel, `StepNode[]` as single source of truth, dnd-kit (ADR 020). Planned: collapse and expand branches, else-if chains, loop iteration views in test results.
- **Workflow execution**: outbox to idempotent jobs, worker with SKIP LOCKED claim and lease, one transaction per step, flat compiled program with jump targets, waiting jobs for approvals, waits and throttle (ADR 008, 021). Planned: child jobs for callable recipes (depth, recursion and step-budget limits), a loop over a step's list output, a Handle errors block scoped to part of a flow.
- **Connector architecture**: built-in executors plus the HTTP step with an egress policy and encrypted, host-bound connections. Planned (ADR 021 section 5): declarative custom connectors imported from OpenAPI, actions and triggers described as data and run through the same HTTP client; dynamic schemas and picklists as part of that model. A Workato-SDK-compatible (Ruby) connector runtime is explicitly not planned.
- **Formula engine**: hand-written tokenizer and parser, no `eval`, fixed function library, hard limits, every datapill read through the caller's path and taint check (ADR 021 section 1). Planned: list `map` and `filter` (needs list-valued outputs), more date and string functions.
- **Datapill engine**: dotted paths into plain JSON below allow-listed roots (`trigger`, `steps`, `recipe`, `job`, `error`, `loop`, `vars`); availability is checked at save time against the steps before it.
- **Triggers**: internal events through a transactional outbox, schedule (interval), manual, signed webhook. Planned: cron expressions and time zones, API-recipe trigger, recipe-function trigger.
- **Job execution and debugging**: redacted per-step input and output, rerun, cancel, dry run with real reads and no writes, health page. Planned: per-iteration loop views, CSV export of the job report.
- **Data**: lookup tables with a trust model (ADR 021 section 2). Workato's data tables page was not read; not planned until it is.

## Security model
Deny by default (admin area `automation`, per-recipe owner and editors, per-connection ACL). Secrets are encrypted, bound to one host and never in definitions or history. User-editable values (first and last name, self-editable attributes, error text, anything read from a recipe-writable lookup table) cannot reach conditions, account changes or variables; this is checked on save and again at run time. Every state change is audited in the same transaction. New features must state how they preserve these invariants (the ADR 021 sections do).

## Deployment architecture
Docker Compose: API, worker (same image, separate command, heartbeat health check), PostgreSQL, Redis, frontend. Recipes and lookup data are tenant-owned rows; migrations by Alembic. Environments and promotion (Workato's lifecycle management) are not designed: JSON export and import is the only mechanism today (WP-027).

## Compatibility assumptions (labelled, not verified against a Workato tenant)
1. The editor layout and interaction follow general knowledge of Workato's recipe editor, not a live comparison (ADR 020).
2. Our formula syntax (`{{= expr }}`) and functions are our own; names overlap Workato's where obvious (string, number, date and list helpers) but there is no promise of identical results.
3. Our lookup tables use a key column, not entry IDs, and have smaller limits than Workato's documented ones (50 tables, 20 columns, 50 000 rows, 4 KB rows).
4. Job statuses differ (ours: queued, running, waiting, succeeded, failed, cancelled; Workato documents completed, failed, processing, paused, aborted) and the default runtime limit is 15 minutes against Workato's documented 90.
5. Workato features not requested here (AI recipe builder, community library, data pipelines, agent recipes) are marked `not_planned`.

## Tradeoffs and risks
- A smaller, safer formula language means recipes cannot be moved to or from Workato.
- No connector catalog means integrations beyond HTTP, Slack and email need the custom-connector work (WP-019) before they are practical.
- Registry upkeep is manual; `report.py` guards structure and file references, not truth. Review `status` whenever a feature PR merges.
- Several pages needed for exact parity (versioning, environments, connection authentication, data pills, SDK structure, API platform) are `not_researched`; those rows are the first research tasks before implementing them.

## Testing strategy
Backend: pytest against a real PostgreSQL schema built by migrations, one test file per feature group, a fuzz test for the formula parser, security tests for taint and tenancy. Frontend: Playwright specs per feature driving the real stack, a throwaway super admin per run (`frontend/e2e`). `tsc` must pass. A feature is `verified` only with both the backend and, where it has UI, the browser tests passing. Gaps found by tests or review are recorded in the registry, not hidden.

## Definition of done (per feature)
Acceptance criteria in the registry met; backend behaviour real and tested; UI (if any) drives the real engine and has a browser test; security invariants stated and tested; migration included if the schema changed; registry entry and `STATUS.md` updated; PR lists what was and was not verified.
