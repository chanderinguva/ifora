# ADR 015: Branding and email templates

Status: accepted (migration 0043). Related: ADR 014 (the `branding` area belongs to organization administrators; read-only administrators can read it).

## Decision
**Branding** (one row per tenant, all fields optional): display name (60 chars), primary colour (`#rrggbb`), sign-in page message (160 chars), and a logo. **Email templates**: the invitation and password-reset emails can be edited (subject and body); no row means the built-in text, which is the wording the product used before this feature.

### Public surface
`GET /api/v1/branding` and `GET /api/v1/branding/logo` are unauthenticated because the sign-in page needs them before anyone is signed in. They expose only what the page already shows. The JSON is `no-cache` (edits appear on the next load); the logo is `public, max-age=300` with an ETag and a `?v=<hash>` URL.

### Why these inputs are safe
- **Logo**: PNG, JPEG or WebP only, identified by file signature, at most 200 KB. SVG is refused (it can carry script) and the image is served with `nosniff`, `Content-Security-Policy: default-src 'none'; sandbox` and a real image content type.
- **Colour**: strict `#rrggbb`, validated on the server and the client, and only ever emitted into a `<style>` block as three numbers (hue, saturation, lightness), never as free text. Text colour on the primary colour is chosen by luminance; in the dark theme a very dark colour is lightened.
- **Name and message**: plain text, no control characters, rendered as text by React (never as HTML).
- **Templates** use a deliberately dumb renderer: `{{first_name}}`, `{{org_name}}`, `{{link}}`, `{{valid_for}}` replaced once, no expressions, loops or recursion. Unknown variables, a missing `{{link}}`, a stray `{{`, control characters, and a multi-line subject are rejected on save. A user's own text (their first name) is inserted verbatim and is **not** re-expanded, and CR/LF are stripped from the rendered subject, so a name cannot add headers or pull in the link twice. Emails are plain text, so nothing is HTML-escaped because nothing is interpreted as HTML.
- A stored template that no longer validates (for example after a rule change) falls back to the built-in text rather than sending a broken email.
- "Send me a test" mails only the signed-in administrator's own address (rate limited), so it cannot be used to mail anyone else.
- Every change is audited (`BRANDING_UPDATED`, `BRANDING_LOGO_SET/REMOVED`, `EMAIL_TEMPLATE_UPDATED/RESET`, `EMAIL_TEST_SENT`).

## Limits
- No custom domain, no custom sign-in page layout, no HTML emails, no per-language templates, no separate dark-theme logo.
- Branding changes the sign-in page, sidebar, consent/continue pages and emails. The browser tab title, favicon and PWA manifest stay "IdentityForge".
- The brand colour is applied to the primary action colour only. An administrator can still pick a low-contrast pairing with the page background in the light theme (for example a very pale colour); the preview shows it before saving.
- Only the two account emails are templated. Recipe `send_email` steps keep their own content.
