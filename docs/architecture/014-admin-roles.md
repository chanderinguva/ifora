# ADR 014: Administrator roles

Status: accepted (migration 0042). Related: ADR 003 (RBAC and sessions), ADR 013.

## Decision
Besides the existing super administrator, an administrator can hold one or more **roles**. Roles are assigned only by super administrators and apply on the administrator's very next request (they are read from the database each time, not cached in the session).

| Role | Can |
|---|---|
| Organization administrator | everything except assigning roles (also the default, below) |
| Read-only administrator | read everything an org admin can read |
| Help desk administrator | change users (status, password, factor resets, invites); read groups, applications, dashboard. Cannot create or delete users |
| Application administrator | manage applications; read users, groups, dashboard |
| Group administrator | manage groups and group rules; read users, dashboard |
| Report administrator | read the system log, users, dashboard |

Roles combine as a union. **An administrator with no role rows is a full organization administrator**, which is how every existing admin keeps working after the migration; assigning any role makes them exactly what the roles allow (to stay full, keep none selected).

## How it is enforced
At the single dependency every admin endpoint already uses (`require_admin`), from the matched **route template** and HTTP method (GET/HEAD/OPTIONS = read, otherwise write), mapped to an area (`users`, `groups`, `applications`, `reports`, `security`, `automation`, `directory_settings`, `overview`, `roles`). Rules:
- Deny by default: a route that maps to no area is refused to everyone except super administrators, so a new admin endpoint is safe before it is classified. A test walks the OpenAPI paths and flags unclassified `/admin` routes.
- Super administrators are never restricted. `roles` is theirs alone.
- The existing target guards still apply on top: a non-super administrator, whatever role, cannot modify another administrator or a super administrator.
- The UI hides navigation the roles do not allow (`GET /me/admin-access`); this is cosmetic, the server is the control.

## Limits
- **No resource scoping yet.** A group administrator manages all groups, not a chosen set; a help desk administrator supports all non-admin users. Okta's resource sets (restrict a role to some groups or apps) are the next step and need per-handler checks.
- **Help desk is powerful by nature**: resetting a non-admin user's password or editing their email can take over that account. Administrators are protected by the target guards; non-admin accounts are not. Treat the role accordingly and watch the system log (`USER_*`, `ADMIN_ROLES_UPDATED`).
- Write-capable pages still show their buttons to read-only roles; the server refuses with "Your administrator role does not allow this".
- Role rows of a user who stops being an administrator stay and apply again if they become one; they are removed with the user.
- `read_only_admin` can read the system log, which can contain sensitive metadata, and can export it.

## Known behaviour: the help desk role can take over ordinary accounts (by design)
`help_desk_admin` may set a password for, reset the sign-in factors of, and unlock any non-administrator account. That is
what a help desk is for, and it also means the role can sign in as those people. Treat it as a privileged role: give it to a
few people, expect every use in the system log (`USER_PASSWORD_CHANGED`, `MFA_RESET`), and keep administrators out of its
reach (it can never act on another administrator).
