# ADR 011: SAML 2.0 identity provider

- Status: Accepted (2026-11-08). Migration 0038. Builds on ADR 010 (applications).
- Libraries: **signxml** (XML-DSig signing and verification; pure Python on lxml + cryptography). No XML canonicalisation, hashing or signature maths is written here. **python3-saml** (xmlsec) is a *test-only* dependency used as an independent strict validator of what we issue.

## What exists
- Application sign-on method **SAML 2.0**; its SAML facet is `saml_providers` (1:1 with the application): SP entity ID, ACS URL, audience, NameID (`email` | `persistent`), what to sign (assertion / response / both, default both), attribute mappings, optional SP certificate (+ "require signed requests"), default RelayState, assertion lifetime (60–3600 s, default 300).
- IdP metadata at `/saml/metadata` (entity ID `SAML_ENTITY_ID`, default `<OIDC_ISSUER>/saml/idp`), SSO endpoint `/saml/sso` (HTTP-Redirect and HTTP-POST bindings in, HTTP-POST binding out).
- **SP-initiated**: AuthnRequest is validated and parked (opaque single-use id, 10 min); the user signs in on the UI page `/saml/continue`; the UI asks `POST /api/v1/saml/requests/{id}/respond` for the signed response and auto-posts it to the registered ACS. **IdP-initiated**: the My apps tile opens `/saml/continue?app=ID` (`POST /api/v1/saml/apps/{id}/respond`).
- Admin UI: SAML card on the application (IdP values to give the SP, import of pasted SP metadata, settings, attributes). Signing certificate: self-signed RSA-2048/SHA-256, private key Fernet-encrypted with `OIDC_KEY_ENCRYPTION_KEY`, created on first use; a super admin can rotate it (the old certificate stays in the metadata until removed, so SPs pinning it keep working).

## Security decisions
- An assertion is only produced for the **signed-in, entitled, active user**, for an **active** application, and is only ever addressed to the **ACS URL an administrator registered** (https, or loopback http). An AuthnRequest naming another ACS is refused, never redirected there. Errors are shown to the user; nothing is sent to an unverified party.
- Requests: DTDs/entities rejected, no network, comments dropped, size capped (256 KB, inflate bounded against zip bombs), `Version`, `ID`, `Destination`, `IssueInstant` (−10 min/+5 min) checked, RelayState ≤ 512 bytes, query parameters must not repeat. Rate-limited per IP like `/oauth/authorize`.
- Signed requests: if a certificate is registered, a present signature must verify (POST: signxml, SHA-1 refused; Redirect: RSA-SHA256 over the exact encoded query string) and "require signed requests" refuses unsigned ones.
- Responses: `InResponseTo`, `Destination`, bearer `SubjectConfirmationData` (`Recipient`, `NotOnOrAfter`), `AudienceRestriction`, unique IDs, `AuthnInstant` = the session's real authentication time, `AuthnContextClassRef` reflects MFA. Persistent NameIDs are an HMAC of (SP, user): stable, and different for every SP. Elements are built with the XML tree API, never string concatenation.
- `ForceAuthn` makes the user sign in again before the response is issued. Single-use pending requests prevent replay of a captured AuthnRequest.
- Attribute sources are an allow-list (email, username, names, groups, `attr:<profile key>`); nothing else on the user (password hash, MFA data) can be mapped. Self-editable profile attributes are mappable: an SP must not treat them as trusted authorisation input (same caveat as group rules, ADR 006).

## Attribute mapping for just-in-time provisioning (step 5, migration 0039)
Applications that create accounts on first sign-in (JIT) read the assertion, so the assertion has to carry what they need.
- Sources per attribute: fixed fields, `attr:<profile key>`, **`expr:<expression>`** (the Okta Expression Language subset of ADR 006: `String.*` functions, `user.<attr>`, ternary; hand-written parser, no eval; 300 characters; checked at save time and evaluated with a sample, a runtime error later means "no value"), and `groups` with an optional **filter** (name equals / starts with / contains; no regular expressions, so no ReDoS).
- **Required** attributes: if a required value (or the NameID) is empty for the user, no assertion is issued and the user sees which items are missing (409), instead of an assertion the SP would reject half-way. Audited as `missing_attributes`.
- NameID can be the email, the username, a profile attribute (format `unspecified`) or the pairwise persistent id.
- Presets (basic, extended) and an admin **preview** (`GET /admin/applications/{id}/saml/preview?user_id=`) show exactly what a user would send, unsigned and without issuing anything.
- Self-editable profile attributes (title, location, bio…) can be mapped. They are the user's own claims, so an SP must not use them for authorisation (same caveat as ADR 006).
- OIDC claim mapping uses a different path (ID token claims) and is not part of this step.

## Known limits
- No Single Logout, no encrypted assertions (TLS protects transport), no artifact binding, no SAML error responses to the SP (a failed request ends on an IdP error page), `IsPassive` is not honoured specially.
- RSA only; single signing algorithm (rsa-sha256).
- Interop is proven against python3-saml in strict mode, not against specific vendor SPs; real SPs (Salesforce, AWS, etc.) are untested.
- Attribute mapping is per-attribute and simple (ADR 010 roadmap step 5 extends it).
