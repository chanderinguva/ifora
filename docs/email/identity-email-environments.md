# Branded identity email and environment identity

## Scope

Every Ifora deployment receives the same codebase and email template catalog. Set the **backend** `ENVIRONMENT` independently on each deployment:

| Deployment | Setting | UI | Identity email subject |
| --- | --- | --- | --- |
| Demonstration | `ENVIRONMENT=demo` | Persistent amber DEMO banner on login and inside app | `[DEMO] Reset your ...` |
| Development | `ENVIRONMENT=development` | Persistent blue DEV banner | `[DEV] Reset your ...` |
| Staging | `ENVIRONMENT=staging` | Blue STAGING banner | `[STAGING] Reset your ...` |
| Tests | `ENVIRONMENT=test` | Blue TEST banner | `[TEST] Reset your ...` |
| Production | `ENVIRONMENT=production` | No warning banner | No prefix |

The environment is reported by the API as `GET /api/v1/branding`. **Never infer it from `NODE_ENV`, the hostname, or localStorage.** Unexpected environment values fail to the nonproduction DEV identity. No change to the production security guardrails is made.

On Docker Compose, use a separate `docker/.env` per deployment; the API and worker now read `ENVIRONMENT` consistently. The `docker-compose.prod.yml` override enforces `production` on the services it controls. Set `demo` explicitly on the demo identity deployment; `--profile demo` launches a *sample OIDC relying party*, not a separate identity tenant.

## Tenant branding

Existing `OrgBranding`, `OrgLogo`, and `EmailTemplate` tables are tenant-owned. The renderer reads branding and template overrides using the provided tenant-scoped database session and does not query across tenants. The reset-email background job now carries the originating tenant ID rather than using the default tenant implicitly.

**Important:** At the time of this enhancement, the HTTP application still resolves its default tenant per request. Full hostname-to-tenant resolution must be implemented and tested separately before marketing this as complete multi-tenant SaaS. Environment identity is a deployment attribute; tenant name, logo, color, and template overrides are tenant attributes. Demo and production must use separate deployments and isolated secrets/data.

## Email compatibility and security

Identity notifications use multipart/alternative `text/plain` plus `text/html`, with a CID-embedded PNG image (converted from uploaded WebP where needed). A bundled Ifora raster icon is used if a tenant has not uploaded a logo. No remote image load is required. The preview substitutes a data URI **only in the sandboxed iframe**, never in the sent message.

HTML uses a 600px max-width table layout, nested presentation tables, inline styles, simple fonts, a mobile viewport, descriptive headings, accessible linked actions and plain-text URLs as fallback. This targets Gmail, Outlook, Apple Mail and browser webmail; pixel-perfect behavior in every client must still be checked with real inbox previews. No executable HTML is accepted from the editor; both text and display values are HTML-escaped. Link CTA destinations allow HTTPS, or HTTP only for localhost in local development. Users must always have plaintext access to action links.

Template substitution remains a nonrecursive allowlist; `{{link}}` and `{{code}}` are required for relevant workflows. No template may control SMTP headers, bypass recipient authorization, or send unapproved messages. Test emails are addressed to the authenticated administrator only.

## Catalog and actual delivery wiring

- **Live:** account invitation, password reset, admin MFA enrollment code. These use the shared renderer on real sends.
- **Ready for integration, not automatically sent:** email verification, account unlock, password changed, security alert, account deactivated. These are editable and previewable; wire each only when the corresponding verified token, identity event, and abuse controls are complete.
- **Out of scope:** recipe-based arbitrary emails. The generic recipe mailer stays plaintext; converting arbitrary recipe output to rich HTML requires separate review of untrusted content.

Existing stored invite/reset overrides are preserved and rendered safely by the new shared layout. No destructive migration is required.

## Rollout checklist

1. Merge the reviewed branch; deploy it separately to DEMO, DEVELOPMENT and PRODUCTION. This PR does not deploy or alter live databases.
2. Confirm the relevant `ENVIRONMENT`, `PUBLIC_APP_URL`, SMTP `From` domain, TLS and tenant branding **per deployment**.
3. Confirm `GET /api/v1/branding` reports the expected `environment`, `environment_label`, and logo revision.
4. Check login and authenticated screens for environment banners; verify production has neither a banner nor non-production prefix.
5. Use the Email templates editor to preview and send tests to an administrator mailbox in Gmail, Outlook desktop/web, Apple Mail, and mobile clients. Confirm CID logo rendering, button links and plaintext fallback.
6. Verify invitation, password reset, and MFA code delivery against their actual protected flows; reject and report wrong-tenant logo or URLs.
7. Confirm SPF, DKIM, DMARC and sending-domain alignment for each SMTP provider (e.g., Brevo). The application alone cannot establish DNS authentication.
8. Monitor for bounce, spam, delivery and rate-limit issues. Keep production secrets and customer data out of demos.
