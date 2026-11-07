# ADR 006: Group rules (attribute-based membership)

- Status: Accepted (2026-11-06). Edition feature flag: `GROUP_RULES_ENABLED` (default on).
- Modelled on Okta group rules; condition language and lifecycle details are ours (Okta's exact semantics were not verified).

## Behaviour
- A rule = name + `all`/`any` + conditions (`attribute`, `operator`, `value`) + one or more target groups. Operators: equals, not equals, starts/ends with, contains, is set, is not set (case-insensitive).
- Rules start **inactive**. Activating applies the rule to every user; afterwards memberships follow user create/update (attributes, status). Only **active users** match.
- Rule-created memberships carry `rule_id`. Manual memberships are never taken over or removed by rules, and a rule-managed membership cannot be removed by hand (409).
- **Deactivating or deleting a rule removes the memberships it created** (deny by default). Active rules cannot be edited; deactivate first.
- System groups cannot be targets. At most 100 rules, 10 conditions each.
- Every change is audited (`GROUP_RULE_*`, and `GROUP_MEMBER_ADDED/REMOVED` with `via_rule`).

## Security decision
Memberships may later drive authorization, so a rule must never be steerable by the user it applies to. Conditions may only use **email, username, status and admin-managed profile attributes**. Self-editable fields (names, phone, title, location, timezone, locale, bio) are rejected when a rule is saved. Conditions are structured data evaluated in code: no expression language, no `eval`.

## Known limits
- Evaluation for one changed user is synchronous in the request. Activating a rule in a directory larger than `GROUP_RULES_SYNC_MAX_USERS` (500) is queued (`sync_state = pending`, cursor in `sync_cursor`) and finished by the worker in batches of `GROUP_RULES_BATCH_SIZE` (200); `python -m backend.cli sync-group-rules` does it by hand. Until it finishes the rule is `active` and the UI shows "syncing". Not yet batched: a user-triggered re-evaluation storm. A rule must be deactivated before it is edited (409 otherwise); activating it again re-evaluates every user, so an edit never leaves stale memberships.
- Admin-managed attributes are free-form keys; there is no schema/catalog yet (the UI suggests department, employee_id, manager, cost_center).
- A manual membership removed later is not re-added by a rule until the user or rule is next evaluated.
- ~~The group-membership table has no `tenant_id`~~ Fixed (migration 0030): the column is filled by a trigger from the group, and the trigger refuses a membership that links a user and a group of different tenants.

## Also in this change
Add person form (groups, organisation attributes, generated one-time temporary password). "Must change password at first login" was added later: the `password_expired` status plus the forced change on login (ADR 007 addendum / `auth/recovery_routes.py`).


## Addendum: expression rules, templates, lifecycle
- **Two rule kinds.** `basic` (structured conditions) and `expression` (an Okta Expression Language subset, `groups/okta_el.py`): hand-written parser, no eval, whitelisted functions (`String.*`, `Arrays.contains/isEmpty/size`, `Convert.toInt`), operators `== != < <= > >= && || ! ?:` plus `eq/ne/lt/le/gt/ge/and/or/not`, `user.<attr>` in Okta camelCase or snake_case (`user.login` = username). Limits: 1000 chars, 150 nodes, depth 20. The self-editable-attribute restriction applies to expressions too. A runtime evaluation error means "no match". Not supported: `isMemberOfGroup*` functions, app-user attributes, array literals. Comparisons are case-sensitive (as in Okta); basic rules stay case-insensitive.
- **Template / export / import.** `GET /admin/group-rules/template` (starter file with both kinds), `GET /export`, `POST /import` (`format: identityforge.group-rules`, v1, groups by name, optional `create_missing_groups`, `dry_run`). All-or-nothing validation; imported rules are always inactive.
- **Lifecycle.** User statuses follow Okta (`staged, provisioned, active, recovery, password_expired, locked_out, suspended, deprovisioned`); only `active` signs in and matches rules. Entering `deprovisioned` removes the user from every group (default, not a recipe).
