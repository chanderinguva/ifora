# ADR 019: Administrator roles through groups, and group standards

## Status
Accepted (builds on ADR 014, administrator roles).

## Decisions

### Roles come from groups (and, as an exception, from the person)
- A **team** group can carry administrator roles (`group_admin_roles`). Every member receives them, on their next request.
- A user's effective roles are the union of the roles assigned to them directly (`admin_role_assignments`) and those carried by their groups (`admin_roles/resolve.py`). The Administrators page and `/me/admin-access` show the source of each role.
- **No role means no administrator access.** The old "no roles = full organization administrator" fallback is removed: with group-carried roles, leaving a group would otherwise promote the person. Migration 0047 gives every existing role-less administrator an explicit `org_admin` role, so nobody loses access when it runs. New administrators start with `read_only_admin`.
- Only super administrators can read or change group roles (`/admin/roles/groups/{id}`, area `roles`).

### Joining a role group is a privilege grant
Membership of a group that carries roles can be changed only by a super administrator, on every path that writes memberships:
admin API (add/remove member, delete group), user creation with groups, group rules (create, edit, import, activate, deactivate, delete), recipes (`add/remove from group` steps refuse) and SCIM (group membership changes refused). Group rules that already target a role group keep working; changing them is super-administrator-only. Only `team` groups can carry roles, and a group carrying roles cannot be re-typed.

### Group standards
Five kinds of group, plus an unclassified default. Machine-readable at `GET /admin/groups/standards`.

| Type | Purpose | Name | Required metadata | Roles |
|---|---|---|---|---|
| `team` | People who work together | `Team - <name>` | owner | allowed |
| `project` | Time-boxed collaboration | `Project - <name>` | owner, review_by | no |
| `app_access` | Entitlement to one application / role | `App - <app> - <role>` | owner | no |
| `push` | Mirrored to a downstream app (SCIM / provisioning) | `Push - <app> - <name>` | none | no |
| `app` | Owned and filled by an integration | as the application names it | none | no |
| `other` | Unclassified (all pre-existing groups) | none | none | no |

Naming is a convention (shown in the UI and the standards document), not enforced. Required metadata is enforced when a group is created, or when its type, owner or review date is changed.

### Group metadata
First-class: `type`, `owner_user_id`, `sensitivity` (low/medium/high), `review_by`, `tags` (<= 10 lowercase labels). Free-form: `attributes`, up to 20 string pairs (key snake_case, value <= 200 characters), for things such as cost_center or application. All are returned by the group API and can be filtered on (`type`, `owner_user_id`, `ownerless`, `sensitivity`, `tag`), so provisioning tools, reports and AI assistants can reason about groups without guessing.

`GET /admin/groups/analytics` summarises the directory: groups by type and sensitivity, unclassified, ownerless (for types that need an owner), empty, review overdue, groups that carry admin roles, largest groups.

## Not done
- Group metadata is not yet exposed through SCIM or to OIDC/SAML claims.
- No access-review campaigns; `review_by` and the overdue count are the hooks for them.
- Types are advisory except for the role and metadata rules above (for example, nothing yet stops assigning a `team` group to an application).
- No resource-scoped roles (e.g. "administers only these apps").
