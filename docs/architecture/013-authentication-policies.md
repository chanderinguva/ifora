# ADR 013: Network zones and per-application authentication policies

Status: accepted (migration 0041). Related: ADR 010 (applications), 011 (SAML), 012 (SWA), 005 (OIDC `amr`/`acr`).

## Decision
An application may have one **authentication policy** with three independent conditions, plus admin-managed **network zones** (named lists of IP/CIDR ranges):

| Condition | Meaning | If not met |
|---|---|---|
| Blocked zones | the client address is in any listed zone | **deny** |
| Allowed zones (non-empty) | the client address must be in one listed zone | **deny** |
| Require MFA | the session's `amr` contains `mfa` (TOTP or passkey) | **re-authenticate** if the user has a second factor, otherwise **deny** with a message to enrol |
| Recent sign-in (5 min to 24 h) | `now - session.auth_time` within the window | **re-authenticate** |

No policy row means no extra conditions. A policy never replaces assignment; both must pass.

## Where it is enforced
One function, `policies.engine.evaluate`, called at every point a token, assertion or credential is issued, not at the page that starts the flow:
- OIDC: `/oauth/authorize` (single-sign-on fast path) and the consent decision.
- SAML: `_respond` (IdP- and SP-initiated).
- SWA: `/swa/apps/{id}/launch`, before the credential is touched.

Pages that explain the situation (`reauth_required`) use a read-only variant so the user is sent to sign in *before* a single-use request is consumed. A deny is audited (`APPLICATION_POLICY_DENIED`); a re-authentication request is not.

## Fail closed
- Order is network, then factor, then freshness, so a blocked network is never offered a step-up.
- An unparsable client address matches no zone (an allow-list denies it).
- An allow-list whose zones were all removed denies everyone. The API refuses to delete a zone a policy still uses.
- IPv4-mapped IPv6 addresses are matched as IPv4.
- Zone and policy changes are audited.

## Limits (be honest about them)
- **Client address** is the TCP peer. Behind a reverse proxy it is the proxy unless uvicorn's proxy-header handling is configured; trusting `X-Forwarded-For` here would let any client forge it. In the Docker dev stack every request appears to come from the Docker gateway.
- **Issued tokens are not revoked** when a policy tightens; refresh tokens (OIDC) and existing SP sessions keep working until they expire. Policy applies when a sign-in completes.
- **`amr` is per session**, so "require MFA" is satisfied by any earlier MFA login in that session, bounded by the recent-sign-in window if set.
- A passkey login counts as MFA (`amr` includes `mfa`, user verification required), matching ADR 005.
- Policies apply to OIDC, SAML and SWA, not to bookmarks (no sign-on happens) or to sign-in to IdentityForge itself.
- Zones are IP-based only: no geography, device posture, risk scoring or ASN.

## Not in this ADR (next)
Organisation-wide password policy (length, complexity, age, history) and session policy (idle and absolute lifetime) need a different mechanism: validators that run without a database session and a per-request lookup, so they are designed separately.
