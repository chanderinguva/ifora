> **Status:** Direction **A, Fold** was selected on 2026-11-06 and integrated into the app. See `guidelines.md`.

# IdentityForge: brand exploration (steps 1-8)

Status: exploration only. No direction selected. Nothing under `frontend/` or `backend/` was touched.
Date: 2026-11-06.

## 1. Brief and assumptions

**Product.** IdentityForge is a self-hosted, custom IAM platform: users, groups, sessions, RBAC, TOTP, passkeys, audit; OIDC planned (docs/project/status.md, CLAUDE.md).
**Name.** "Identity" (the irreducible self) + "Forge" (raw material shaped under heat and pressure into something trusted). Sound: hard consonants, two strong stresses, short enough to monogram as "IF".
**Audience (assumed).** Buyers: engineering leads, security/platform teams, self-hosters. Daily users: admins (dashboards, audit, RBAC) and end users (login, MFA, sessions). The tone should be calm, exacting, and trustworthy rather than "cyber".
**Current UI (read from repo).** The header has plain text "IdentityForge" in Lora (`app-shell.tsx`), no logo or favicon mark. The login page is text only. `globals.css` uses shadcn-style HSL tokens. Light: background `0 0% 100%`, foreground/primary `222.2 84% 4.9%` (about #020817). Dark: background #020817, foreground `210 40% 98%` (about #F8FAFC). Tailwind `darkMode: class`; Lora is mapped to sans, serif and mono. There is no accent colour. Light/System/Dark is being added (theme-toggle.tsx is untracked).
**Personality (assumed).** Restrained, editorial (the serif choice signals this), precise, quietly confident. A scholarly-but-engineered feel, not a startup-gradient feel.
**Competitors/references.** Okta, Auth0, Ping Identity, Microsoft Entra (also Keycloak, Authentik, Zitadel, WorkOS as the open/dev tier).
**Assumptions to confirm.** (1) Monochrome-first with at most one accent. (2) Keep Lora for the wordmark. (3) A mark is needed for favicon and the app-shell header at about 20-28 px. (4) No clarifying round was needed because concepts are colour-agnostic.
**Could not determine.** Target market positioning (enterprise vs. developer), whether OIDC branding will become a standalone product name, and any existing domain or trademark filings.

## 2. Landscape and cliche audit

Caveat: web search returned only weak sources (an Auth0 blog post on rebrand alignment with Okta, and aggregator pages). Competitor mark descriptions below come from the brief and general knowledge and are **unverified**; check the brands' press kits before relying on them.

- **Category conventions.** Shields, padlocks, keyholes, fingerprints, "person in a circle", key shapes, check-marks in badges, hexagon grids, circuit traces, blue/purple/teal palettes, ring-of-dots or node networks.
- **Named references.** Okta: circle with dots motif. Auth0: shield/star. Ping Identity: flame/wave. Microsoft Entra: multi-colour interlocking diamond/gem. Auth0 and Okta have been aligning on rounded shapes and a shared type approach (per Auth0's own branding post).
- **Overused-symbol list.** Shield, padlock, keyhole, fingerprint, key, person-in-circle, check inside shield, ring of dots, hexagon, circuit line, sparkle, blue-to-purple gradient.
- **Open territory.** (a) Serif-led, editorial identity in a sea of geometric sans. (b) Constructed mono marks with an explicit rule (grid, quarter-circles, folds). (c) Marks about assembly and verification, not protection or secrecy. (d) A strict black/white identity with an optional single accent, rare in IAM where blue dominates.

## 3. Concept board (seven concepts)

Grid for all constructions: 64 x 64 viewBox. Colour: monochrome `currentColor`, so it follows the near-black/white tokens.

### A. Fold (monogram, single path) [SVG: concepts/forge-fold.svg]
- **Idea.** An "F" forged from one uniform-width bar that is folded twice, plus a solid dot, the "i" of identity, resting where the F's foot would be. Reads "IF", or "F." with the dot as the one point that is you.
- **Rule.** Stroke 9 (about 14% of the grid). Bar: (48,14) to (22,14) to (22,52), mitre join. Arm: (22,33) to (40,33). Dot: centre (46,47), r 6.5. All edges on integer or half-integer coordinates.
- **Metaphor.** Forge (a bar bent into shape) and identity (the point). A bent strip also suggests an assertion folded into a token.
- **Colour.** Mono. Optional single accent on the dot only.
- **Wordmark.** "IdentityForge" in Lora semibold, the F aligned to the mark's stem.
- **16x16.** Strong; chunky shapes survive (confirmed in the preview render). Risk: reads as "F." with a full stop at small sizes.
- **Vs. references.** No circle motif, shield, flame or gem; is a letterform.

### B. Quorum (systemic/modular, quarter-circles) [SVG: concepts/quorum.svg]
- **Idea.** Four quarter-disc tiles make one circle. Three sit in place and the fourth is docked a few units off-register: factors or apps assembling into one verified identity, with the last piece still arriving.
- **Rule.** Centre (32,32), radius 24, gap 3 between tiles. Three tiles on the true grid. The fourth is shifted +4,+4 along the diagonal. Each tile is the same quarter-disc rotated 90 degrees.
- **Metaphor.** Many parts, one self (federation); multi-factor quorum; modular and animatable (the tile slides home on success, a natural loading and verification animation).
- **Colour.** Mono; the displaced tile could take the accent.
- **Wordmark.** Lora, set small beside the mark.
- **16x16.** Reads as a quartered circle; the offset is only just visible (see preview). Needs a simplified small version with a bigger offset.
- **Vs. references.** A "circle made of parts" is the nearest territory to Okta's circle; the quarter-tile construction and offset keep it distinct but risk is real.

### C. Overlap (negative space/intersection) [SVG: concepts/overlap.svg]
- **Idea.** A square (the system) and a circle (the person) overlap. Only the intersection is solid: identity exists where a person and a system meet and agree.
- **Rule.** Square outline 35.5 wide at (7.5,7.5); circle r 18.5 centred on the square's bottom-right corner (43,43), so the intersection is exactly a quarter disc. Stroke 5.
- **Metaphor.** Trust as the verified overlap of two parties; authentication as the intersection of claim and system.
- **Colour.** Mono; fill the intersection with an accent if one is adopted.
- **16x16.** Weakest of the three: 5/64 stroke is about 1.2 px at 16 px and the intersection shrinks to about 4 px (see preview). Needs a heavier small variant.
- **Vs. references.** Venn-like overlaps are common, but square + circle with a corner-centred quarter disc is specific. Nothing from the four named brands.

### D. Convergence (custom symbol)
- **Idea.** Many short strokes of different lengths enter a ring-less circle from the edges and end on one solid centre dot: a constellation resolving to a point.
- **Rule.** Nine rays at 40-degree steps, lengths from a fixed ratio series (1, 0.8, 0.6 repeating), converging on a r 7 dot.
- **Metaphor.** Many apps, one identity.
- **Risks.** Looks like a sun or asterisk; node networks are a category cliche. 16x16: poor (rays merge). Not developed.

### E. Temper (experimental, mark as transformation)
- **Idea.** A three-state mark: square (raw input), square with rounded corners (forged), circle (verified identity). Static logo is the middle state; the app animates square to circle during login.
- **Rule.** Superellipse with corner radius stepping 0, 12, 32 on a 48-unit square.
- **Metaphor.** The forge as transformation.
- **Risks.** Static form is bland (rounded square resembles an app icon); depends on animation. 16x16: acceptable but generic. Not developed.

### F. Serif I (typographic-only)
- **Idea.** Wordmark-led: Lora "IdentityForge" with a custom "I" whose slab serifs are merged into a single H-bar shape, and a solid dot replacing the tittle of the "i" in "Identity".
- **Rule.** Cap height 100, stem 14, serif length 34; dot diameter equal to stem x 1.15.
- **Metaphor.** Editorial restraint; fits the existing Lora identity with zero new visual language.
- **Risks.** No standalone mark for favicon (would fall back to a monogram "I" or "F"), and Lora is a common free font. Not developed.

### G. Clasp (abstract geometry, interlock)
- **Idea.** Two identical right-angle brackets (L-shapes) rotated 180 degrees, hooked into each other with a square gap: a verified handshake without hands.
- **Rule.** Stroke 10, arm 36, hook offset 10, 180-degree rotational symmetry about the centre.
- **Metaphor.** Mutual verification, closure and stability.
- **Risks.** Resembles chain-link or "link" icons and interlocking marks such as Entra's interlock idea; medium originality risk. 16x16: good. Not developed.

## 4. Evaluation (1-5, 5 is best; originality risk: 5 = lowest risk)

Contrast checked: #020817 on white 20.0:1 and #F8FAFC on #020817 19.1:1, both far above the 3:1 graphic and 4.5:1 text thresholds. Marks carry meaning by shape, not colour.

| Concept | Distinctiveness | Scalability (16/32, 1-colour) | Contrast/accessibility | Light/dark | Originality risk | Fit | Total |
|---|---|---|---|---|---|---|---|
| A Fold | 4 | 5 | 5 | 5 | 4 | 5 | 28 |
| B Quorum | 4 | 3 | 5 | 5 | 3 | 5 | 25 |
| C Overlap | 3 | 2 | 5 | 5 | 3 | 4 | 22 |
| D Convergence | 2 | 1 | 4 | 5 | 2 | 3 | 17 |
| E Temper | 2 | 3 | 5 | 5 | 4 | 3 | 22 |
| F Serif I | 3 | 2 | 5 | 5 | 4 | 4 | 23 |
| G Clasp | 3 | 4 | 5 | 5 | 2 | 4 | 23 |

Scores are my judgement from the construction and the one preview render of A-C; D-G were not drawn, so their numbers are estimates. C ranks below G and F on total, but I keep it in the top three because it is the only concept whose idea (overlap = verified identity) maps directly to the product story; B and G are the closest alternatives.

## 5. Top three (stop point: please choose)

**1. A, Fold.** Why: best legibility (confirmed at 16 px in the preview), builds directly on the Lora/editorial tone, ownable "IF" letterform with a narrative (forged bar plus the point of identity), simplest to produce in SVG/ICO. Strengths: favicon-ready, mono, easy lockups. Risks: at small sizes the dot reads like a full stop ("F."), and single-letter marks are easy to confuse with other "F" brands; needs similarity search. Colour/type: #020817 / #F8FAFC, optional accent on the dot; Lora semibold wordmark.

**2. B, Quorum.** Why: best systemic story (assembling factors, animatable verification). Strengths: strong at 32 px and up, natural motion for login success. Risks: offset is subtle at 16 px (needs a small-size variant with a larger offset or a gap-only version), nearest to Okta-style "circle" territory. Colour/type: mono plus an accent on the displaced tile; Lora regular wordmark.

**3. C, Overlap.** Why: the clearest concept, "identity is where person and system agree". Strengths: unique construction, accessible, easy to explain. Risks: weak at 16 px with thin strokes (needs a heavier small variant), Venn-like overlap is a familiar device. Colour/type: mono, accent in the intersection.

**Recommendation: A, Fold.** It is the most scalable, fits the existing serif UI, and carries the name (IF, forge, identity point) in a single glyph. Use the Quorum tile motion as a later animation language only if you like it. This is a design recommendation; nothing is final until you choose. I have not integrated anything.

Preview render: `docs/brand/preview.png` shows A-C at 128/32/16 px on white and near-black (rendered with headless Google Chrome). Observations from it: A holds up best; B's offset nearly vanishes at 16 px; C's stroke is thin at 16 px.

## 6. Image-generation prompts (top three)

No image-generation tool was invoked in this session (see section 8). Paste these yourself and send results back for validation. Common avoid list: sparkles, shield, padlock, keyhole, fingerprint, gradient, 3D bevel, drop shadow, mockup scene, stock icon, text, outline glow.

### A. Fold
**Recraft Vector.** "Flat vector logo mark, 1:1, centred on white. A bold capital letter F constructed from a single uniform-width bar: horizontal top bar, vertical stem, and a shorter middle arm, mitred sharp corners, all strokes the same thickness (about 14% of the canvas). A solid circle sits at the lower right where the F's foot would be, diameter slightly larger than the stroke. Solid #020817 only, no gradients, no text, no outlines, clean closed paths, geometric, minimal. Negative: sparkles, shield, padlock, keyhole, gradient, bevel, shadow, mockup, stock icon, rounded corners, serif letterform."
**ChatGPT Images.** "Logo mark only, square 1:1, flat near-black (#020817) on pure white. A geometric letter F built from one folded bar of constant thickness with sharp mitred corners, plus a solid dot resting in the lower-right empty space as the 'i' of identity. Heavy negative space, perfectly aligned edges, no text, no gradient, no 3D, no mockup, no shield, lock, keyhole or sparkle. Looks like a constructed brand symbol, not an icon-pack glyph."
**Ideogram (wordmark/lockup).** 'Horizontal logo lockup: a geometric F-and-dot symbol on the left, and the wordmark "IdentityForge" on the right in a refined transitional serif (Lora-like, semibold), tight tracking, near-black #020817 on white, flat vector, 3:1 aspect ratio. Text exactly: "IdentityForge". No gradients, no shield, no lock, no icon clutter.'

### B. Quorum
**Recraft Vector.** "Flat vector logo mark, 1:1, centred on white. A circle made of four identical quarter-disc tiles separated by thin equal gaps; three tiles sit in place, the bottom-right tile is displaced diagonally outward by about one tile-gap and a half, as if still arriving. Pure geometry, exact arcs, solid #020817, no gradient, no text, clean paths. Negative: sparkles, shield, padlock, keyhole, gradient, 3D, shadow, mockup, dots ring, stock icon."
**ChatGPT Images.** "Logo mark only, 1:1, near-black on white. A circle split into four quadrant tiles with narrow gaps, the fourth tile slightly offset diagonally to suggest assembly. Flat, geometric, no text, no gradient, no 3D, no mockup, not a pie chart, not a loading spinner."
**Ideogram.** 'Stacked lockup: quadrant-circle symbol above the wordmark "IdentityForge" in a Lora-like serif, centred, #020817 on white, flat vector, 1:1. Exact text: "IdentityForge". No gradient, no extra icons.'

### C. Overlap
**Recraft Vector.** "Flat vector logo mark, 1:1, centred on white. An outlined square and an outlined circle of equal stroke weight overlapping; the circle's centre sits exactly on the square's bottom-right corner so the overlap is a quarter disc, which is filled solid. Only the overlap is solid. #020817, no gradient, no text, clean paths. Negative: sparkles, shield, padlock, keyhole, gradient, Venn diagram colours, 3D, shadow, mockup, stock icon."
**ChatGPT Images.** "Logo mark only, 1:1. Square outline and circle outline intersecting; the intersection is a solid filled quarter circle, everything else is outline. Near-black #020817 on white, thick even strokes, flat, minimal, no text, no gradient, no mockup."
**Ideogram.** 'Horizontal lockup: square-and-circle overlap symbol left, wordmark "IdentityForge" right in a Lora-like serif, #020817 on white, flat vector, 3:1. Exact text: "IdentityForge".'

## 7. Similarity and trademark notes (preliminary; not legal advice)

I did not run a trademark database or reverse-image search. This is a reasoned comparison only, based on the brief and general knowledge (competitor marks unverified, see section 2).
- **vs. Okta (circle/dots).** A: low (letterform). B: medium (circle-based, but tiled and offset, no dots). C: low-medium (contains a circle, but square-based).
- **vs. Auth0 (shield/star).** A, B, C: low.
- **vs. Ping Identity (flame/wave).** A, B, C: low.
- **vs. Microsoft Entra (interlocking gem).** A: low. B: low. C: low-medium (overlapping geometric shapes, but outline and non-gem).
- **Generic-form risk.** Single-letter F marks and quartered circles are crowded across software; I expect medium risk in Nice classes 9, 42 and 45 for A and B until searched. C is likely low-medium.
- **Not covered.** Name availability for "IdentityForge" and "Identity Forge" (several unrelated "Forge" products exist in software), domain/registry status, and design-mark searches (EUIPO TMview, USPTO, WIPO Global Brand Database).
- **Recommendation.** Uniqueness is not guaranteed. Commission a professional trademark clearance search, covering word and design marks in classes 9, 42, 45, before public launch.

## 8. Generation tooling, validation and gaps

- **Image generators.** None were used. Figma `generate_image` and Weave model tools exist in this session but I did not use them (no instruction, possible cost and account effects). The prompts above are ready for Recraft, ChatGPT Images and Ideogram; no generated asset exists.
- **SVGs hand-authored by me.** `concepts/forge-fold.svg`, `concepts/quorum.svg`, `concepts/overlap.svg`. Each has a viewBox, a `<title>`, `currentColor`, no text, no scripts or external references.
- **Mechanical check.** The grep (`<script|on[a-z]+=|javascript:|foreignObject|<!DOCTYPE|<!ENTITY|https?://|xlink:href|<image`) matched only the `xmlns="http://www.w3.org/2000/svg"` line in each file. `xmllint --noout --nonet` parsed all three. `defusedxml` is not installed, so I relied on xmllint plus grep. The files are my own, so the hardened-parser rule was not strictly required.
- **Rendering.** Previewed with headless Google Chrome into `docs/brand/preview.png` (white and near-black, 128/32/16 px). I viewed it. Not done: PNG/ICO exports, SVGO, maskable or apple-touch-icon.
- **Not done by design.** No brand system, tokens, lockups, clear-space rules or frontend integration until a direction is selected.
