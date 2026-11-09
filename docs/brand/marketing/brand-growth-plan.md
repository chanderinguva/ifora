# IdentityForge brand growth plan (marketing view)

Status: proposal, written from the repo and general market knowledge. No market research, competitor verification or trademark search was done. The approved identity (monochrome "Fold" mark, Lora wordmark, see `../guidelines.md`) is unchanged; everything here is additive.

## Positioning
**For** platform and security teams that want to own their identity layer **IdentityForge is** a self-hosted IAM that covers the Okta-style essentials (SSO, MFA, passkeys, provisioning, policies, audit) **unlike** SaaS identity vendors, you keep the data, the code and the keys.
Proof points we can honestly make today: OIDC provider, SAML IdP, SCIM server, passkeys + TOTP, group rules, per-app policies, admin roles, system log, one-command Docker Compose deploy.
Do not claim: certifications, independent security audit, scale numbers, or interoperability we have not tested (no real SAML SP interop yet).

## Brand idea: "Forged, not rented"
Identity is made under pressure into something trustworthy. Voice: calm, exacting, plain-spoken; show the mechanism, not buzzwords.
Tagline candidates: **Identity, forged in-house.** / **Own your identity layer.** / **Every sign-in, hallmarked.** (pairs with the Hallmark mark)

## Marks (this folder)
| File | Use |
|---|---|
| `01-ember` | Primary marketing mark: Fold mark + ember dot (`#F97316`). Web, docs, slides. |
| `02-ember-tile` | App icon / avatar on any surface (GitHub org, social). |
| `03-hallmark` | Seal for trust moments: release notes, security pages, certificates, stickers. |
| `04-ingot` | Weakest concept (F is cramped); keep as a sticker idea only. |
| `05-spark` | Campaign and launch graphics (the dot throws sparks). Too detailed below 24 px. |
| `06-ember-block` | High-impact banners and conference swag. |
| `*-light.svg` | Light-ink versions for dark backgrounds. |
Rule: the ember accent is for marketing surfaces only. The product UI stays monochrome per the guidelines. Contrast: `#020817` on `#F97316` is about 7:1; white on `#F97316` is only about 2.8:1, so never set white text on ember.
`png/` holds 512 px exports on a transparent background for the Branding page (which accepts PNG, JPEG and WebP, not SVG).

## 90-day initiatives
1. **Foundations (weeks 1-2):** one-page site (positioning, comparison table, deploy in 5 minutes), README rewrite, GitHub social preview from `06-ember-block`, public roadmap (the Okta parity roadmap, trimmed).
2. **Proof (weeks 3-6):** publish the threat model and the independent-review result with fixes; "how we built passkeys / SAML / SCIM" engineering posts; demo tenant with seed data and a 3-minute video.
3. **Community (weeks 6-10):** Show HN / r/selfhosted launch, a migration guide "from Okta/Keycloak CSV and SCIM", templates for common apps (the app catalogue already exists).
4. **Credibility (weeks 8-12):** commission an external penetration test and OIDC/SAML conformance runs; publish results. Trademark search for the name and mark (Nice classes 9, 42, 45) before any paid campaign.
Measure: repo stars and clones, docs visits to "deploy" page, time-to-first-login in the quickstart, issues from people outside the team.

## Risks
- "Forge" and "Identity" are common words; trademark conflict is possible and unchecked.
- A self-hosted IAM is judged on security first; marketing ahead of the external audit would backfire.
- Two colour systems (monochrome product, ember marketing) must be kept apart or the identity blurs.
