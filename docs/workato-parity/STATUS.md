# Workato parity status

Generated from `features.yaml` (reviewed 2026-11-09) by `report.py`. Do not edit by hand. Design: `docs/architecture/022-workato-parity.md`.

48 features. verified: 16, implemented: 4, partial: 16, not implemented: 10, blocked: 1, not planned: 1.
Research: complete: 15, partial: 14, not researched: 19.

`verified` means the acceptance criteria are covered by automated tests that passed when this was last reviewed. Nothing here claims exact parity: where Workato behaviour was not read, the feature says so.

| ID | Feature | Status | Research | Priority | Main gaps |
|---|---|---|---|---|---|
| WP-001 | Recipe creation and management | verified | partial | high | No folders, projects, tags or search (WP-026) |
| WP-002 | Vertical recipe editor (studio) | implemented | not researched | high | Collapse and expand branches; No side-by-side comparison with Workato (built from general knowledge, ADR 020) … |
| WP-003 | Recipe lifecycle and versioning | implemented | not researched | high | No version comments; No diff between versions … |
| WP-004 | Triggers | verified | partial | high | Triggers exist only for IdentityForge events, schedule and webhook (no third-party app triggers); No polling triggers |
| WP-005 | Actions | verified | complete | high | Action set is IdentityForge-specific plus HTTP; Slack and email; no catalog of third-party apps |
| WP-006 | Connector selection and catalog | not implemented | partial | medium | Needs the connector model of WP-019 first |
| WP-007 | Connection management | verified | not researched | high | No OAuth authorization-code flow (WP-018); Runtime-user connections not designed |
| WP-008 | Datapills and field mapping | verified | not researched | high | No type-aware filtering of formulas by pill type; No per-iteration list pills |
| WP-009 | Formula mode and functions | verified | partial | high | Workato formula mode is per-field Ruby with allow-listed methods; ours is a different closed language so formulas are not portable (compatibility assumption, ADR 022); Function names only partly match Workato's string, number, date, list and complex-type formulas … |
| WP-010 | Conditional logic | partial | complete | high | No ELSE IF chain (nest instead); Nesting limited to 3 levels |
| WP-011 | Loops | partial | complete | high | Only "for each member of a group" exists; No repeat while … |
| WP-012 | List processing | partial | not researched | high | No list-valued step outputs; No map/filter/sort/unique … |
| WP-013 | Variables | verified | not researched | medium | No list or map update operations |
| WP-014 | Error handling | partial | partial | high | Handler is recipe-wide, not a block around chosen steps (needs an engine change); Handler cannot wait or loop |
| WP-015 | Retry policies | verified | partial | medium | No configurable backoff; No retry of a block |
| WP-016 | Callable recipes and recipe functions | not implemented | partial | high | Designed in ADR 021 section 3; async calls and wait-for-async not designed |
| WP-017 | HTTP and REST connector | verified | partial | high | No pagination; No GraphQL or SOAP helpers … |
| WP-018 | Authentication types | partial | not researched | medium | No authorization-code flow; No basic auth … |
| WP-019 | Custom connector SDK | not implemented | partial | high | ADR 021 section 5 plans OpenAPI import, not a Ruby SDK; SDK internals not researched; Workato-SDK compatibility is not a goal |
| WP-020 | Dynamic schemas and picklists | not implemented | not researched | medium | Depends on the connector model |
| WP-021 | Job execution | verified | complete | high | No paused status after a recipe is stopped; Runtime limit default differs from Workato … |
| WP-022 | Job history and debugging | partial | complete | high | No per-iteration navigator for loops; No CSV export of the job report … |
| WP-023 | Recipe testing | verified | not researched | high | Cannot test a single step in isolation |
| WP-024 | Lookup tables | partial | complete | medium | Different limits from Workato's; Entries addressed by key not entry ID … |
| WP-025 | Data tables | not implemented | not researched | low | Not researched |
| WP-026 | Projects and folders | not implemented | not researched | medium | Not researched |
| WP-027 | Environments and deployment | partial | not researched | medium | No environments, packages, promotion or diff; Connections and lookup tables are not exported |
| WP-028 | Access control | verified | not researched | high | No per-project roles; Workato privilege model not compared |
| WP-029 | Auditing | verified | not researched | high | — |
| WP-030 | Monitoring and alerts | implemented | not researched | medium | No metrics endpoint verified; No external alert delivery |
| WP-031 | API management (API recipes) | not implemented | partial | medium | Listed in ADR 021 as roadmap |
| WP-032 | Scheduling and polling | partial | partial | medium | No cron expressions, no time zones, no polling triggers |
| WP-033 | Webhooks and event processing | verified | not researched | high | Workato webhook options not compared |
| WP-034 | Wait, delay and throttle | verified | not researched | medium | No wait for an event or date; Concurrent workers racing the throttle not tested |
| WP-035 | Stop job and approvals | verified | partial | medium | Approval has no Workato counterpart researched |
| WP-036 | Code steps (Python, Ruby, JavaScript) | blocked | not researched | high | Five sandbox, package, permission, network and tenancy decisions are open (ADR 021 section 4) |
| WP-037 | AI assistance, community library, data pipelines, agents | not planned | partial | low | Documented by Workato; not requested for IdentityForge |
| WP-040 | String formulas (documented methods vs ours) | partial | complete | medium | Missing: is_not_true?, is_true?, match?, parameterize, lstrip, rstrip, scrub, strip_tags, ljust, rjust, reverse, scan, encode, transliterate, capitalize, titleize, quote, bytes, bytesize, byteslice, ordinalize, to_country_alpha2, to_country_alpha3, to_country_name, to_currency, to_currency_code, to_currency_name, to_currency_symbol, to_phone, to_state_code, to_state_name |
| WP-041 | Number formulas (documented methods vs ours) | partial | complete | medium | Missing: **, even?, odd?, to_currency, to_phone |
| WP-042 | Date and datetime formulas (documented methods vs ours) | partial | complete | medium | Missing: wday, yday, yweek, beginning_of_hour, beginning_of_day, beginning_of_week, beginning_of_month, beginning_of_year, end_of_month, in_time_zone, dst?, to_i |
| WP-043 | List formulas (documented methods vs ours) | partial | complete | medium | Missing: index, where, except, pluck, format_map, smart_join, concat, reverse, sum, uniq, flatten, max, min, compact |
| WP-044 | Complex data type (hash) formulas (documented methods vs ours) | partial | complete | low | Missing: pluck |
| WP-045 | Trigger mechanisms: polling, real-time, scheduled, change data capture | partial | complete | medium | No polling triggers (needs third-party connectors, WP-019); No change data capture … |
| WP-046 | Trigger dispatch types: single, batch, bulk | not implemented | complete | medium | Needs list-valued data (WP-012) and loops over lists (WP-011) first; Bulk (CSV streaming) is not planned |
| WP-047 | Trigger conditions (AND/OR filters) | implemented | complete | medium | Not checked against Workato's documented late-evaluation caveat (records updated later to match may be missed); ours filters the event as emitted |
| WP-048 | Trigger processing order, concurrency and from-date | partial | partial | low | Concurrency is a server setting, not per recipe; No from-date (our triggers are push events, not polled history) |
| WP-049 | RecipeOps connector (monitor recipes, jobs and the account from a recipe) | not implemented | not researched | low | Not researched |
| WP-050 | Job report: columns, CSV export, rerun rules, paused and pending jobs | not implemented | complete | low | Workato: reruns use the latest recipe version; ours reruns the stored definition; No paused state when a recipe is stopped and no 30-day pending expiry |

## Documented method coverage (our equivalent exists, may differ in behaviour)

| ID | Category | Covered | Documented |
|---|---|---|---|
| WP-040 | String formulas | 18 | 49 |
| WP-041 | Number formulas | 15 | 20 |
| WP-042 | Date and datetime formulas | 7 | 19 |
| WP-043 | List formulas | 5 | 19 |
| WP-044 | Complex data type | 0 | 1 |

## Research gaps (documentation not read; not a decision to omit)

- Recipe editor UI (tried /en/recipes/recipe-editor: 404)
- Error handling (monitor, retry, error types) (tried /en/recipes/error-handling: 404; only the Handle errors one-liner on /en/recipes/steps was read)
- Recipe versioning and version history (tried /en/recipes/versioning: 404)
- Recipe lifecycle management: environments, packages, projects, folders (tried /en/recipe-lifecycle-management: 404)
- Formula syntax: datapill references in formulas, null handling (tried /en/formulas/formula-mode: page read; reference syntax and null handling not covered)
- Connector SDK structure, authentication types, testing tools (tried /en/developing-connectors/sdk: overview only; /en/developing-connectors/sdk quickstart not read)
- Connections and authentication types (tried /en/connections (linked, not fetched): not fetched)
- Data pills and data tree (tried none: not fetched)
- Recipe function inputs, outputs, limits and error behaviour (tried /en/connectors/recipe-functions: overview only; action pages not read)
- Recipe concurrency, change data capture, bulk triggers (tried /en/recipes/triggers: named, details on pages not read)
- Webhook trigger configuration (tried /en/connectors/workato-webhooks/config (linked): not fetched)
- API platform: API recipes, endpoints, collections, authentication, rate limits (tried /en/api-mgmt/api-recipes (linked): not fetched)
- Data tables (tried none: not fetched)
- Workspace administration: roles and privileges, audit log, data retention, quotas (tried none: not fetched)
- Workbot for Slack, AIRO, community library, data pipeline and genie recipes (tried /en/recipes (linked): listed only; recorded as not planned in WP-037)

## Next candidates (high priority, dependencies in place)

- WP-010 Conditional logic: No ELSE IF chain (nest instead)
- WP-011 Loops: Only "for each member of a group" exists
- WP-012 List processing: No list-valued step outputs
- WP-014 Error handling: Handler is recipe-wide, not a block around chosen steps (needs an engine change)
- WP-016 Callable recipes and recipe functions: Designed in ADR 021 section 3; async calls and wait-for-async not designed
- WP-019 Custom connector SDK: ADR 021 section 5 plans OpenAPI import, not a Ruby SDK; SDK internals not researched; Workato-SDK compatibility is not a goal
- WP-022 Job history and debugging: No per-iteration navigator for loops
