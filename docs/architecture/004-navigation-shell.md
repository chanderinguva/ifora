# ADR 004: Application shell and navigation

## Decision
Persistent **left sidebar** (brand lockup on top, grouped destinations below) plus a **top bar** (sidebar toggle, breadcrumbs, theme, account menu). Collapsible to an icon rail on desktop; an overlay drawer on small screens.

## What the identity products do (research, 2026-11)
| Product | Observed pattern | Source |
| --- | --- | --- |
| Okta Admin Console | Menu moved to the left (2021 redesign); search along the top of every page | [Okta blog](https://www.okta.com/blog/product-innovation/oktas-redesigned-admin-console-and-dashboard-now-in-ga/) |
| Microsoft Entra admin center | Left-hand menu plus a top search bar; organised by product | [Microsoft Learn](https://learn.microsoft.com/entra/fundamentals/entra-admin-center) |
| Auth0 Dashboard | Left sidebar with labelled groups (Integration, Customization, Security & Monitoring...), sticky action bar with breadcrumbs, tabs, actions and sidebar toggle; profile top-right; sidebar state persisted | [Auth0 docs](https://auth0.com/docs/get-started/auth0-overview/dashboard/use-dashboard-navigation) |
| Keycloak admin console | Logo top-left of the sidebar with the realm selector beneath (older console; current layout not verified) | secondary sources |

General guidance: a top-left logo that links home, ideally with a visible Home destination ([NN/g](https://nngroup.com/articles/homepage-links/)); collapsed rails keep the current page marked, show tooltips and give icons accessible names, and large layouts switch to an overlay below ~768 px (design-system docs such as [UCL](https://www.ucl.ac.uk/brand-and-experience/experience/ucl-design-system/components/side-bar) and [Singapore Gov](https://designsystem.tech.gov.sg/components/sidebar)).

Confidence: the left-sidebar pattern is well supported. Details of the logo area in Okta/Entra were not documented in the sources found, and several accessibility points come from design-system docs rather than a standard, so they are treated as good practice, not rules.

## What we do
- **Logo + name top-left, links home**; same height as the top bar so the dividers align. Collapsed rail shows the mark only (it is legible at 16 px).
- **Grouped nav** with labels (Directory, Security, Account); current page via `aria-current` and an indicator bar.
- **Top bar**: sidebar toggle (state persisted in `localStorage`, `aria-expanded`), **breadcrumbs** from the URL (ids read "Details"), theme switch, account menu.
- **Collapsed rail**: icon-only items keep their name as `aria-label`; tooltips on hover **and keyboard focus**; animation respects `prefers-reduced-motion`.
- **Mobile (<768 px)**: hamburger opens a dialog drawer (`aria-modal`), focus moves in and is trapped, Escape/backdrop/choosing a link close it and focus returns to the opener; body scroll locked.
- **Skip to main content** link; `main` is focusable.
- Role context (admin / user view) lives in the account menu label and the user-view banner, not in the sidebar header.

## Not done (deliberately)
- ~~Global search~~ **Done later:** Cmd/Ctrl+K command palette and a Search button in the header (admins): jumps to any page and searches users, groups, applications (OIDC clients), recipes and group rules (`GET /admin/search`, 5 per kind, literal matching).
- **Realm/tenant selector** (Keycloak/Auth0): single-tenant for now.
- Nested/expandable nav groups: the IA is small enough to be flat within labelled groups.

## Verification
`frontend/e2e/nav.spec.ts` (logo link, groups, breadcrumbs, collapse + persistence + tooltip on keyboard focus, skip link, mobile drawer focus handling, no horizontal scroll). Visual review in light/dark and at 390 px. No automated colour-contrast or screen-reader audit has been run.
