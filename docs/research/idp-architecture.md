# How major identity providers architect their features

_Research notes, 2026-11-06. Purpose: inform IdentityForge's roadmap, starting with the OIDC provider (ADR 005)._

## How to read this
- **Confidence** is marked per claim: **H** = standard/primary doc or consistently reported; **M** = vendor docs/secondary summaries that agree; **L** = single secondary source or inferred. Several sources were vendor blogs and mirrors; where a summary was ambiguous (e.g. the exact RFC 9700 keyword for the implicit grant) it is flagged rather than guessed.
- Not researched in depth (gaps): Entra token/sign-in log schemas and key rollover, Auth0 organizations/connections, Okta device-assurance and behavior-detection policies, PingFederate, SAML, social/federation brokering, delegated admin. Treat anything about those as unknown.
- This is architecture research, not a feature wishlist. Each section ends with what it means for IdentityForge.

## 1. Cross-vendor patterns

| Area | Common pattern | Seen in | Conf. |
|---|---|---|---|
| App model | Separate "application/client" (config) from its runtime identity (service principal / client credentials). Entra splits app registration (global definition) from enterprise app / service principal (per-tenant instance + consent + assignment). | Entra, Okta, Auth0 | M |
| Login/consent delegation | Authorization server redirects to a separate login/consent UI; the server stores the pending request and hands the UI a challenge id, rather than trusting raw query params. Ory Hydra is the canonical example (login challenge → accept → consent challenge → accept). | Hydra, Keycloak (built-in), Auth0 | M |
| Authorization servers | Okta supports multiple "custom authorization servers" per org, each with its own issuer, scopes, claims and access policies. Most others have one issuer per tenant/realm. | Okta, Keycloak (realm), Entra (tenant) | M |
| Policy layering | Authentication policy ("how must this user sign in", with factor constraints incl. phishing resistance, applied per app and tiered by app sensitivity) is distinct from authorization policy (scopes/claims per client). Entra Conditional Access sits in front of both. | Okta, Entra | M |
| Refresh tokens | Rotation with reuse detection (replay revokes the family) is the default recommendation for public clients. | Auth0, Okta, RFC 9700 | M/H |
| Extensibility | Hooks at login/token time (Auth0 Actions, Okta inline hooks, Keycloak SPIs/mappers) to add claims or deny. | Auth0, Okta, Keycloak | M |
| Provisioning | SCIM 2.0 outbound/inbound plus lifecycle states (staged, active, suspended, deprovisioned). | Okta, Entra, others | M |
| Audit | Append-only event log with actor, target, outcome, client, IP, and a stable event-type taxonomy; exported via API/streaming. Okta System Log is the reference shape. | Okta, Entra, Auth0 | M |
| Keys | Per-tenant signing keys, published at JWKS, rotated on a schedule with overlap so old tokens verify until expiry. | all | H |
| Conformance | OpenID Foundation certification via the conformance suite (Basic/Config OP profiles). | Okta, Keycloak, ZITADEL, Ory | M |
| Architecture style | Keycloak and Ory favour modular/service-based; ZITADEL is event-sourced (audit falls out of the event store) and multi-tenant by design. | Keycloak, Ory, ZITADEL | L/M |

## 2. Standards the OIDC provider should honour (and what is known)
- **RFC 9700 (OAuth 2.0 Security BCP, Jan 2025):** exact redirect-URI matching; PKCE recommended for all clients; no tokens returned from the authorization endpoint (implicit grant discouraged; summaries disagree whether the RFC says SHOULD NOT or MUST NOT, so confirm in the RFC text); resource-owner-password grant deprecated; public-client refresh tokens must be sender-constrained or rotated with reuse detection. **Conf. M** (secondary summaries; verify against rfc-editor.org/rfc/rfc9700).
- **Step-up and re-auth:** `acr_values` and `max_age` are the parameters for requesting stronger/fresher authentication. If `max_age` is sent the ID token must carry `auth_time`; the relying party still has to validate it. `prompt=login` alone is weak because a client cannot rely on it having forced re-authentication. **Conf. M.**
- **`amr` (RFC 8176):** list of method strings (`pwd`, `otp`, `hwk`, `fpt`, `mfa`, …). Parties must agree on meanings; vendors disagree on whether `acr` or `amr` is the better trust signal, so IdentityForge must document exactly how it populates both. **Conf. M.**
- **Okta app sign-in policies:** per-app rules can require N factor types and phishing-resistant possession constraints; guidance is to tier apps by sensitivity. Device-context and behaviour-detection details were not found. **Conf. M.**

## 3. Mapping to IdentityForge
What we already have that lines up: opaque server-side sessions, TOTP/passkey factors, a "require passkey" policy, admin MFA policy, audit events, groups. What the research says is missing, in rough priority:
1. Record `auth_time` and the actual methods (`amr`) on the session at login. Required before any ID token can be honest.
2. An application/client registry with exact redirect URIs, PKCE required, consent records.
3. Stored pending authorization requests (Hydra-style) instead of re-trusting query params across the login redirect.
4. Rotating refresh tokens with family revocation on reuse.
5. Per-application sign-in policy (required factor strength, max session age) layered on the existing policies. Natural second milestone after OIDC.
6. Audit taxonomy for OIDC events (client created, consent granted/revoked, token reuse detected, key rotated).
7. Later: SCIM, SAML, claim/token hooks, SSF/CAEP-style session signals. Not designed yet.

## 4. Sources (as returned by search; not all read in full)
- RFC 9700 summaries: phasetwo.io, django-oauth-toolkit docs, workos, scalekit; primary: rfc-editor.org/rfc/rfc9700
- RFC 8176 and IANA registry: rfc-editor.org/rfc/rfc8176, iana.org (authentication-method-reference-values)
- Step-up/max_age: auth0.com/docs/authenticate/login/max-age-reauthentication, ssojet, logto docs
- Okta phishing-resistant sign-in policies: help.okta.com (pr-set-up-policies, pr-overview)
- Earlier-session searches (Hydra login/consent, Keycloak concepts, Entra app registration/Conditional Access, Auth0 refresh rotation/Actions, Okta System Log, SCIM, JWKS rotation, OpenID conformance, ZITADEL): findings summarised in §1 at confidence M or L; re-verify specifics before relying on them in implementation.

## 5. End-user account settings (added 2026-11-06)
What the competitors expose to the signed-in user (conf. M unless noted; Okta's help page did not confirm which profile fields are editable, and Entra's menu names vary by tenant and portal version):

| Area | Okta End-User Settings | Entra My Account | IdentityForge now |
|---|---|---|---|
| Personal info | Editable per admin config; editing requires re-verification with two enrolled authenticators | Profile + photo | Names + self-editable attributes (re-verification **not** done) |
| Language / region | Display language separate from the profile `locale`; user's saved choice wins | "Language & Region": display language, time zone (admin may lock language) | Time zone and locale dropdowns (this PR); interface still English only |
| Security methods | Authenticators list | Security info (add/remove methods, default method) | Authenticator app, passkeys, recovery codes |
| Devices / sessions | — | Devices | Active sessions (no per-session revoke yet) |
| Recent activity | Recent activity | My sign-ins, with "this wasn't me" on unusual ones | Recent activity card (this PR); no "report unusual" |
| Privacy | — | "View how your organization uses your data" | none |

Gaps worth building next, in rough priority: revoke individual sessions; step-up re-verification before editing sensitive profile data or removing factors; "this wasn't me" on activity; admin-lockable profile fields (per-attribute self-service policy); profile photo; preferred/display name; default MFA method; privacy/data-use page.
