# IdentityForge brand guidelines

**Selected direction: A, "Fold" (forge-fold).** Chosen by the project owner on 2026-11-06 from three finalists (see `concepts.md`).
Not a trademark clearance: a professional search for the name and mark (Nice classes 9, 42, 45) is still recommended before launch.

## The mark
An "F" forged from one bar of constant width, folded twice, plus a solid dot, the "i" of identity. It reads "IF" or "F.".

Construction (64-unit grid, `docs/brand/assets/mark.svg`):
- Bar: stroke width **9**, mitred corners, butt ends. Path `M48 14 H22 V52` (stem and top arm) plus `M22 33 H40` (middle arm).
- Dot: circle **r = 6.5** at **(46, 47)**, sitting where the F's foot would be.
- Never redraw by eye; scale the SVG. Do not add outlines, shadows, gradients or a container shape to the mark itself.

## Colour
The mark is a single colour and always takes the surrounding text colour (`currentColor`). Two fixed colours exist:

| Use | Light surface | Dark surface |
| --- | --- | --- |
| Mark and wordmark | `#020817` (near-black) | `#F8FAFC` (near-white) |
| Contrast on its surface | 20.0 : 1 on white | 19.1 : 1 on `#020817` |

These match the app's design tokens (`--foreground` in light and dark), so the logo follows the theme with no per-theme files. No accent colour; the identity is deliberately monochrome.

## Typography
The wordmark is **IdentityForge** in **Lora SemiBold (600)**, tight tracking (`tracking-tight`), set as live text so it stays in the app font. Lora is the product typeface everywhere; do not substitute another font for the wordmark.

## Lockups and sizes
- **Mark only**: tabs, avatars, tight spaces. Minimum **16 px** (verified legible at 16 px). Below 16 px use the favicon/tile.
- **Horizontal lockup**: mark + wordmark, gap ≈ 0.35 × mark height; wordmark cap height ≈ the F's stem height. Components: `Logo` (`size="md"` 28 px mark / `"lg"` 40 px mark) in `frontend/src/components/logo.tsx`.
- **Clear space**: at least the width of the bar (9 units, ≈ 1/7 of the mark) on every side.
- **App icon / tile**: near-black `#020817` full-bleed square with the white mark at 70 % scale (maskable variant at 56 % to survive circular masks). No transparency, so it reads on any launcher.

## Files
| File | Purpose |
| --- | --- |
| `docs/brand/assets/mark.svg` | Master, `currentColor` (follows context) |
| `docs/brand/assets/mark-black.svg`, `mark-white.svg` | Fixed-colour monochrome variants |
| `docs/brand/assets/mark-black-512.png`, `mark-white-512.png` | Transparent PNGs |
| `docs/brand/assets/app-tile.svg`, `app-tile-maskable.svg` | App icon sources |
| `frontend/src/app/icon.svg` | Browser-tab favicon; carries its own `prefers-color-scheme: dark` rule |
| `frontend/src/app/favicon.ico` | 16/32/48 fallback (tile style) |
| `frontend/src/app/apple-icon.png` | 180 px touch icon |
| `frontend/public/icons/icon-192.png`, `icon-512.png`, `icon-maskable-512.png` | Web app manifest icons (`src/app/manifest.ts`) |

There is no outlined wordmark SVG: the wordmark is live Lora text in the app. If a static lockup is needed (print, social), set "IdentityForge" in Lora SemiBold and convert to outlines in a design tool.

## Do / don't
- Do keep the mark one colour and let it follow the theme.
- Do keep Lora for the wordmark.
- Don't add gradients, glows, 3D or outlines; don't rotate, skew or recolour part of the mark.
- Don't place the dot elsewhere or change the bar width.
- Don't use the tile style (dark square) on already-dark surfaces; use the white mark instead.

## Validation
All SVGs: no scripts, event handlers, external references, DOCTYPE/ENTITY or raster images (checked by grep and `xmllint --noout --nonet`). The browser test `frontend/e2e/brand.spec.ts` checks the mark's paint is `currentColor`, light/dark colours, Lora on the wordmark, and that the favicon, apple icon and manifest are served.

## Limits
Favicon theming relies on the browser honouring `prefers-color-scheme` inside an SVG favicon (Chrome and Firefox do; Safari may show the light variant). The ICO, apple and manifest icons use the tile and are theme-independent.
