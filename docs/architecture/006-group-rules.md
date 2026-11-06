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
- Evaluation is synchronous in the request that changes a user (fine for small directories); activation scans all users. A background worker is the next step for large directories.
- Admin-managed attributes are free-form keys; there is no schema/catalog yet (the UI suggests department, employee_id, manager, cost_center).
- A manual membership removed later is not re-added by a rule until the user or rule is next evaluated.
- The group-membership table has no `tenant_id`; rule and group rows are tenant-scoped.

## Also in this change
Add person form (groups, organisation attributes, generated one-time temporary password). "Must change password at first login" is **not** implemented (needs a user flag and login enforcement).
