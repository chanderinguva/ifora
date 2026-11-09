# Agent handoff (keep short; update at every checkpoint)

**Last updated:** 2026-11-09. Standing rules: commits have no Claude co-author line; PR bodies end with the Claude Code line; never merge without explicit authorisation; never print secrets; no subagents unless asked; ask before `docker stop`; one test or e2e run at a time; do not delegate to FreeLLMAPI without the one-time approval from the global instructions.

## State
- Merged to `main`: formulas (#65), variables/wait/throttle (#66).
- Open, not merged (do not merge without approval): **#67 lookup tables** (branch `feature-recipe-lookup-tables`, commit `70342ea`); **#68 docs** (branch `docs-workato-parity`, base is the #67 branch).
- Registry now 48 features + 15 research gaps (formula method coverage per documented category, trigger mechanisms). Formula coverage is computed in STATUS.md.
- Parity design: `docs/architecture/022-workato-parity.md`; registry `docs/workato-parity/features.yaml`; report `docs/workato-parity/STATUS.md` (regenerate with `python3 docs/workato-parity/report.py`, needs PyYAML or macOS ruby).

## Next (high priority, dependencies in place, per STATUS.md)
Active task after the docs PR: **WP-012 then WP-011**: list values in step outputs, formula list functions (`pluck`, `sum`, `uniq`, `reverse`, `index`, `compact`, `concat`), and a Repeat step over a list.
1. WP-011/WP-012 list-valued step outputs and a loop over them (unblocks map/filter and callable recipes).
2. WP-016 callable recipes (ADR 021 section 3).
3. WP-014 Handle errors block scoped to part of a flow (engine change).
4. WP-010 else-if chains; WP-022 per-iteration loop views and job report CSV.
Research first (not_researched): versioning, environments, connection authentication, data pills, SDK structure, API platform.
Blocked: WP-036 code steps need the five sandbox decisions in ADR 021 section 4 from the owner.

## How to run things (macOS, Docker)
`SC=/private/tmp/claude-501/-Users-chanderinguva-Development-identityforge/60f081b3-7326-44ec-b03f-28fb73637f2d/scratchpad` must be exported in every Bash call.
- Backend: `docker compose -f docker/docker-compose.yml build backend-api` (tests are baked into the image), then `$SC/t8.sh -q -p no:warnings tests/<file>.py > $SC/t.log 2>&1` (paths relative to `backend/`; a pass prints dots only).
- Browser: `$SC/e2e_run.sh <spec>.spec.ts ... > $SC/e.log 2>&1` (rebuilds, makes and deletes a throwaway super admin); read the result from the log, strip colour codes with `sed -e 's/\x1b\[[0-9;]*m//g'`.
- Type check: `cd frontend && ./node_modules/.bin/tsc --noEmit`.
- Recipe regression set: `backend/tests/test_recipe*.py test_recipes*.py`, e2e `recipes recipes-m6 recipe-studio recipe-studio-dnd recipe-studio-pills recipe-studio-test recipe-studio-formulas recipe-studio-flow-steps recipe-lookup-tables`.
- Full backend suite takes about 55 minutes and has not been run for the formula, flow-step or lookup work.

## Blockers and cautions
- Context compaction and `/clear` are user-side commands; the agent cannot run them. Resume from this file after `/compact` or a new session.
- Keep the Mac awake for long runs: `caffeinate -i -s -w <claude pid>` in another terminal (no system settings are changed).
