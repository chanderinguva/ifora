# Okta parity roadmap

Written from general knowledge of the Okta Admin Console and End-User Dashboard (not a live comparison against a tenant).
Status: **Done** / **Partial** / **Todo**. Work in order; each phase is one PR.

## Admin console (Okta navigation)
| Okta area | Okta features | IdentityForge |
|---|---|---|
| Dashboard | Tasks, usage/health widgets, system log trend, org status | Partial: counts and recent activity; needs widgets and a tasks list |
| Directory > People | Search/filter, bulk actions, statuses, activate/suspend/unlock, reset password/factors, detail tabs | Partial: statuses, status filter, **bulk activate/suspend/unsuspend/unlock/deactivate, Applications and Activity tabs (phase 3)**; Todo: bulk add-to-group, Devices tab |
| Directory > Groups | Rules, push groups, role assignment | Partial: groups, rules; Todo: group detail tabs (People, Applications, Admin roles) |
| Directory > Profile Editor | User/app profile, mappings | Partial: user profile; Todo: per-app profile + attribute mapping UI |
| Directory > Directory Integrations | AD/LDAP agents | Todo (out of scope until a connector is needed) |
| Applications > Applications | Create App Integration wizard, catalog, tabs (General, Sign On, Assignments, Provisioning, Push Groups, Import) | Done: wizard, tabbed page, 16-entry bookmark catalog. Todo: SSO-capable catalog entries, Push Groups, Import |
| Applications > Self Service | Request/approve | Todo |
| Security > Authenticators | Enrol policy per factor | Partial: TOTP, passkeys; Todo: factor catalogue, email OTP |
| Security > Authentication policies | Per-app sign-on policy: network, group, device, factor, re-auth frequency | Todo (largest gap) |
| Security > Global session policy | Session lifetime, MFA at sign-in, rules | Partial: fixed idle timeout; Todo: configurable policy |
| Security > Password policy | Length, complexity, age, history, lockout | Partial: fixed rules; Todo: configurable |
| Security > Network zones | IP allow/block lists | Todo |
| Security > Administrators | Roles, custom roles, resource sets | Partial: admin / super admin; Todo: scoped roles |
| Security > API tokens, Trusted origins | | Todo |
| Workflow | Workflows, tasks | Partial: Recipes |
| Reports > System log | Filter, search, export, detail drawer | Partial: audit list with filter; Todo: export, detail drawer, saved search |
| Settings > Customization | Branding (logo, colours), custom domain, sign-in page, email templates | Todo |
| Settings > Account / Features / Downloads | | Todo |

## End-user dashboard
| Okta | IdentityForge |
|---|---|
| App tiles, search, launch | Done |
| Sections / tabs ("Work", "Add section") and drag-reorder | Todo |
| Recently used, favourites | Todo |
| Add-apps / request access | Todo |
| Notifications and tasks | Todo |
| Settings page: personal info, security methods, password, recovery | Partial: Account settings |
| Activity ("Recent activity" on sign-ins) | Todo |
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
