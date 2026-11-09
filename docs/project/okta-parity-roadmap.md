# Okta parity roadmap

Written from general knowledge of the Okta Admin Console and End-User Dashboard (not a live comparison against a tenant).
Status: **Done** / **Partial** / **Todo**. Work in order; each phase is one PR.

## Admin console (Okta navigation)
| Okta area | Okta features | IdentityForge |
|---|---|---|
| Dashboard | Tasks, usage/health widgets, system log trend, org status | Done (phase 5): Tasks (7 live checks), 7-day sign-in chart, users by status, apps by sign-on method. Todo: org health/status, customisable widgets |
| Directory > People | Search/filter, bulk actions, statuses, activate/suspend/unlock, reset password/factors, detail tabs | Partial: statuses, status filter, **bulk activate/suspend/unsuspend/unlock/deactivate, Applications and Activity tabs (phase 3)**; Todo: bulk add-to-group, Devices tab |
| Directory > Groups | Rules, push groups, role assignment | Partial (ADR 019): groups, rules, **group types and metadata (owner, sensitivity, review date, tags, attributes), admin roles assigned through team groups**, standards and analytics endpoints. Todo: group detail tabs (Applications), push-group sync, access reviews |
| Directory > Profile Editor | User/app profile, mappings | Partial: user profile; Todo: per-app profile + attribute mapping UI |
| Directory > Directory Integrations | AD/LDAP agents | Todo (out of scope until a connector is needed) |
| Applications > Applications | Create App Integration wizard, catalog, tabs (General, Sign On, Assignments, Provisioning, Push Groups, Import) | Done: wizard, tabbed page, 16-entry bookmark catalog. Todo: SSO-capable catalog entries, Push Groups, Import |
| Applications > Self Service | Request/approve | Partial (phase 10, ADR 017): per-app switch, request with reason, approve/deny queue, dashboard task. Todo: email notices, approver groups, expiry |
| Security > Authenticators | Enrol policy per factor | Partial: TOTP, passkeys; Todo: factor catalogue, email OTP |
| Security > Authentication policies | Per-app sign-on policy: network, group, device, factor, re-auth frequency | Partial (phase 6, ADR 013): per-app allow/block network zones, require MFA, recent sign-in; enforced at OIDC, SAML and SWA. Todo: group- and device-based rules, rule ordering, policy simulation |
| Security > Global session policy | Session lifetime, MFA at sign-in, rules | Partial (phase 6b, ADR 018): configurable lifetime and idle timeout, lockout; applied to open sessions. Todo: MFA-at-sign-in rules, per-group rules |
| Security > Password policy | Length, complexity, age, history, lockout | Done (phase 6b, ADR 018): length, case/digit/symbol, no name/email, history, max age, lockout. Todo: breached-password check, per-group policies |
| Security > Network zones | IP allow/block lists | Done (phase 6): CIDR zones, used by app policies. Todo: dynamic zones (geo, proxies) |
| Security > Administrators | Roles, custom roles, resource sets | Partial (phase 7, ADR 014): six built-in roles (org, read-only, help desk, app, group, report) enforced centrally, assigned by super admins to people or to team groups, applied immediately; no role means no access. Todo: resource sets (scope to some groups/apps), custom roles, role-aware buttons |
| Security > API tokens, Trusted origins | | Todo |
| Workflow | Workflows, tasks | Partial: Recipes |
| Reports > System log | Filter, search, export, detail drawer, saved search | Done (phase 4): search, time range, action list from API, target filter, detail drawer, CSV export (audited, formula-safe), saved filters (per browser). Todo: server-side saved filters, scheduled exports, streaming to SIEM |
| Settings > Customization | Branding (logo, colours), custom domain, sign-in page, email templates | Partial (phase 8, ADR 015): name, logo, primary colour, sign-in message; editable invite and reset emails with preview and test send. Todo: custom domain, sign-in layout, HTML emails, more templates |
| Settings > Account / Features / Downloads | | Todo |

## End-user dashboard
| Okta | IdentityForge |
|---|---|
| App tiles, search, launch | Done |
| Sections / tabs ("Work", "Add section") and drag-reorder | Done (phase 9, ADR 016): own sections, move earlier/later and section menu (keyboard-friendly instead of drag and drop), stored on the account |
| Recently used, favourites | Done (phase 9): favourites group, last-30-days recents row, old browser pins imported once |
| Add-apps / request access | Done (phase 10): Request access page and My requests |
| Notifications and tasks | Todo |
| Settings page: personal info, security methods, password, recovery | Partial: Account settings |
| Activity ("Recent activity" on sign-ins) | Done (phase 9): own sign-in and credential events on the dashboard |
| Org branding on dashboard | Todo |

## Order of work
1. **Create App Integration wizard** (this PR) and tabbed application page (General, Sign On, Assignments, Provisioning).
2. Application catalog (pre-built SAML/OIDC/SWA templates) with logos.
3. People lifecycle: statuses, suspend/unlock, bulk actions, user detail tabs.
4. System log upgrade: detail drawer, export, saved filters.
5. Admin dashboard widgets and Tasks.
6. Authentication policies per app (network zones, group, factor, re-auth) plus global session and password policies.
7. Admin roles with scopes.
8. Branding and email templates.
9. End-user dashboard: sections, favourites, recents, activity.
10. Self-service access requests.
