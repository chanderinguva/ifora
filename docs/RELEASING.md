# Releasing

IdentityForge is deployed with Docker Compose, so a release is a git tag plus release notes; there is no package to publish.

## Cadence
- **Weekly**, Mondays 09:00 UTC, `.github/workflows/release.yml` prepares a **draft** GitHub release from `main` when `main`
  has commits since the last release. It first runs the same checks as every PR (`ci.yml`: frontend type-check, backend tests).
- Versions are date-based: `v2026.11.16`; a second release the same day is `v2026.11.16.1`.
- An unpublished draft from the week before is deleted and replaced, so there is never more than one draft.
- Run it on demand from Actions → Weekly release → Run workflow (tick *force* to release with no new commits).

## Publishing
1. Open the draft under Releases, read the generated notes, edit anything unclear (label PRs `security`, `feature`, `fix`,
   `docs` to group them; `skip-changelog` hides one).
2. Check the notes for **database migrations** and new **environment variables**; add upgrade steps if there are any.
3. Press **Publish**. That creates the tag on the commit the draft was prepared from.

## Upgrading a deployment
`git fetch --tags && git checkout <tag>`, then `docker compose -f docker/docker-compose.yml up -d --build`. Migrations run
on API start.

## Rollback and hotfixes
- Migrations must be safe to roll **forward** (additive first, drop later). Rolling back the code to the previous tag is
  safe only if the newer migrations were additive; say so in the notes when a release is not safely reversible.
- Hotfix: branch from the released tag, fix, merge to `main` through a PR, then run the workflow with *force* and publish.

## What the checks do not cover
Playwright e2e (needs the whole stack) is run by hand before publishing: `cd frontend && npx playwright test`.
