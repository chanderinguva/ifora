# Workato parity status

Generated from `features.yaml` (reviewed 2026-11-09) by `report.py`. Do not edit by hand. Design: `docs/architecture/022-workato-parity.md`.

37 features. verified: 16, implemented: 3, partial: 9, not implemented: 7, blocked: 1, not planned: 1.
Research: complete: 6, partial: 13, not researched: 18.

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

## Next candidates (high priority, dependencies in place)

- WP-010 Conditional logic: No ELSE IF chain (nest instead)
- WP-011 Loops: Only "for each member of a group" exists
- WP-012 List processing: No list-valued step outputs
- WP-014 Error handling: Handler is recipe-wide, not a block around chosen steps (needs an engine change)
- WP-016 Callable recipes and recipe functions: Designed in ADR 021 section 3; async calls and wait-for-async not designed
- WP-019 Custom connector SDK: ADR 021 section 5 plans OpenAPI import, not a Ruby SDK; SDK internals not researched; Workato-SDK compatibility is not a goal
- WP-022 Job history and debugging: No per-iteration navigator for loops
