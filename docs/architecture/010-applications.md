# ADR 010: Applications (one object for sign-on, assignment and provisioning)

- Status: Accepted (2026-11-07). Migration 0035.
- Modelled on Okta's application object; details are ours.

## Model
- `applications`: name (unique per tenant), description, `sign_on_mode` (`none` | `bookmark` | `oidc`), `launch_url`, `status` (`active`|`inactive`), `visible` (shown on My apps), `require_assignment`.
- `application_assignments`: user XOR group, one row per subject per application (partial unique indexes). **One list drives everything**: who may sign in, who sees the tile, who is provisioned.
- Facets attach to an application: an OIDC client (`oidc_clients.application_id`, at most one) and an outbound provisioning app (`provisioning_apps.application_id`, exactly one, `ON DELETE RESTRICT`). The old `provisioning_assignments` table is gone; the provisioning assignment endpoints are wrappers over the application's assignments.
- Entitlement = assigned directly or through a group (`applications/entitlement.py`). Provisioning additionally needs an `active` user (ADR 009).

## Behaviour
- Creating an OIDC client creates its application (`require_assignment=false`, so upgrading never locks anyone out; visible unless it is a service client). Creating a provisioning app creates an application with sign-on `none`. Deleting the last facet of such an application deletes it; an application with provisioning attached cannot be deleted (409).
- `/oauth/authorize` and the consent decision refuse (`access_denied`) when the application is inactive, or requires assignment and the user is not entitled.
- **My apps**: `GET /me/apps` lists entitled, active, visible applications that have a sign-on method. `POST /me/apps/{id}/launch` re-checks entitlement, audits `APPLICATION_LAUNCHED` and returns the launch URL; an unassigned or missing app answers the same 404. Launch URLs must be http(s) without embedded credentials. The UI (user dashboard and `/apps`) shows tiles with search and per-browser pinned favourites.
- All changes are audited (`APPLICATION_*`).

## Logos (step 2)
- `application_icons` (migration 0036), kept out of the application row. Admins upload PNG/JPEG/WebP (≤100 KB, checked by file signature; **SVG is refused** because it can carry script) as base64 JSON. Served by our API only (`/admin/applications/{id}/icon`, `/me/apps/{id}/icon` for entitled users) with `nosniff`, `default-src 'none'` CSP and private caching, so no user's browser contacts a third-party image host. The tile falls back to a coloured initial.
- Image dimensions are not checked or resized server-side.

## OIDC templates and IdP-initiated launch (step 3, migration 0037)
- `GET /admin/applications/templates`, `POST /admin/applications/from-template`: **web** (confidential, secret), **SPA** and **native** (public, PKCE, no secret), **service** (client credentials, super admin only, no tile). One transaction creates the application and its client; the secret is returned once. Templates default to `require_assignment = true` (the plain client API keeps `false` for compatibility). Validation is the existing client validation, so a failed template creates nothing.
- Native apps: https app-links or loopback `http://127.0.0.1` redirects only. **Custom URL schemes (RFC 8252 private-use) are not supported yet.**
- `oidc_clients.initiate_login_uri` (https, or loopback http): launching the tile sends the user to it with `iss` and, if a launch URL is set, `target_link_uri` (OIDC third-party initiated login). The application then starts its own authorization-code flow with state and PKCE. IdentityForge never sends an unsolicited code or token, and no user data is in the URL. An OIDC app is launchable if it has a launch URL or an initiate URI.

## Known limits
- Revoking an assignment does not revoke OIDC tokens already issued.
- No database trigger enforces that an assignment's user/group belong to the same tenant (single tenant today).
- Bookmark tiles are plain links; no credential injection (SWA) exists. SAML sign-on is described in ADR 011.
- Pins are stored in the browser only.

## Roadmap (agreed order)
2. Bookmark polish, 3. OIDC templates (web/SPA/native/service) and IdP-initiated launch, 4. SAML 2.0 IdP (mature library), 5. SSO attribute mapping/JIT, 6. SWA (optional, security review first).


Update: step 6 of the roadmap, **Secure Web Authentication**, is ADR 012 (migration 0040).
