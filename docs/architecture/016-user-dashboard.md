# ADR 016: End-user dashboard (sections, favourites, recents, activity)

Status: accepted (phase 9 of `docs/project/okta-parity-roadmap.md`)

## Decision
Per-user dashboard preferences live in PostgreSQL, not in the browser:

- `user_app_sections` (user, name, position; max 10 per user, unique name per user).
- `user_app_prefs` (user, application, favourite, section, position, last_launched_at, launch_count). Deleting a section sets its apps back to "Other" (`ON DELETE SET NULL`); deleting a user or application cascades.

API (`/api/v1/me/dashboard`, signed-in user only):
`GET` overview, `POST/PATCH/DELETE /sections`, `PUT /apps/{id}` (favourite, section, move earlier/later), `POST /import-favorites`, `GET /activity`.
`POST /me/apps/{id}/launch` records the launch in the same transaction as the audit event, after entitlement is proven.

## Security properties
- Entitlement stays the only thing that makes an app appear. A preference never grants or reveals anything; the overview drops preferences for apps the user cannot currently see (unassigned, inactive, hidden), and `PUT /apps/{id}` answers 404 for them.
- Sections are checked against the caller's id; another person's section id gets the same 404 as a missing one, so ids cannot be probed.
- Recents are the last 30 days, at most 6, and only for launches that succeeded.
- `GET /activity` returns only the caller's own sign-in and credential events (sign in/out, failed sign-in, password, MFA and passkey changes), as action, time and IP. It never returns admin actions about the user, other people's events, or event details.
- The old browser-only pins (`localStorage` key `if.pinned-apps`) are imported once, filtered through the same visibility check, then removed.

## Accessibility
Reordering uses "move earlier/later" buttons and a "Section" select instead of drag and drop, so it works by keyboard and screen reader.

## Not done
Drag and drop, per-section colours, notifications and tasks, add-apps/request access (phase 10), admin-pushed default sections.
