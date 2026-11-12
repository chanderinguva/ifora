#!/usr/bin/env bash
# One command to put the latest origin/main on the demo and on the local dev/prod stack.
#
#   scripts/deploy.sh status         what each stack runs vs origin/main (read-only)
#   scripts/deploy.sh                deploy everything that is behind, then verify
#   scripts/deploy.sh demo           deploy only the demo (demo.ifora.app)
#   scripts/deploy.sh local          deploy only the local dev/prod stack (ifora.app)
#   scripts/deploy.sh all            deploy both, even if they look current
#
# Merging a PR deploys nothing; this does. It always builds origin/main (never your working tree), reloads the demo
# edge so Caddyfile changes apply, waits for the frontend to come up, and records what it deployed.
#
# The local stack's env file and compose override live outside the repo; override the defaults if yours differ:
#   LOCAL_ENV=~/Development/ifora/docker/.env  LOCAL_OVERRIDE=~/Development/ifora-app-local/ifora-app.yml
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEMO_HOME="${DEMO_HOME:-$HOME/ifora-demo}"
LOCAL_ENV="${LOCAL_ENV:-$HOME/Development/ifora/docker/.env}"
LOCAL_OVERRIDE="${LOCAL_OVERRIDE:-$HOME/Development/ifora-app-local/ifora-app.yml}"
LOCAL_SHA_FILE="${LOCAL_SHA_FILE:-$HOME/.ifora-local-deployed-sha}"
LOCAL_SERVICES=(backend-api frontend recipes-worker) # the edge is a stock image; the rest are data stores

die() { echo "deploy: $*" >&2; exit 1; }
say() { echo "deploy: $*"; }

target() { git -C "$REPO" fetch -q origin main; git -C "$REPO" rev-parse origin/main; }

# "up to date", or how far behind a deployed sha is.
state() { # deployed-sha target-sha
  local d="$1" t="$2"
  if [ -z "$d" ]; then echo "unknown (never deployed by this script)"; return; fi
  if [ "$d" = "$t" ]; then echo "up to date"; return; fi
  local n; n="$(git -C "$REPO" rev-list --count "$d..$t" 2>/dev/null || true)"
  [ -n "$n" ] && echo "behind by $n commit(s)" || echo "different from origin/main"
}

demo_sha()  { cat "$DEMO_HOME/deployed-sha" 2>/dev/null || true; }
local_sha() { cat "$LOCAL_SHA_FILE" 2>/dev/null || true; }

cmd_status() {
  local t; t="$(target)"
  printf 'origin/main  %s\n' "${t:0:9}"
  printf 'demo         %-9s  %s\n' "$(demo_sha | cut -c1-9)" "$(state "$(demo_sha)" "$t")"
  printf 'local        %-9s  %s\n' "$(local_sha | cut -c1-9)" "$(state "$(local_sha)" "$t")"
  for c in ifora-demo-api ifora-api; do
    printf '%-14s %s  ENVIRONMENT=%s\n' "$c" "$(docker inspect -f '{{.State.Status}}' "$c" 2>/dev/null || echo missing)" \
      "$(docker exec "$c" printenv ENVIRONMENT 2>/dev/null || echo '?')"
  done
}

deploy_demo() {
  "$REPO/scripts/demo.sh" deploy
}

deploy_local() {
  [ -f "$LOCAL_ENV" ] || die "missing $LOCAL_ENV (set LOCAL_ENV)"
  local sha files
  sha="$(target)"
  src="$(mktemp -d)"
  trap 'rm -rf "${src:-}"' EXIT # global on purpose: the trap runs after this function has returned
  git -C "$REPO" archive "$sha" | tar -x -C "$src"
  files=(-f "$src/docker/docker-compose.yml")
  [ -f "$LOCAL_OVERRIDE" ] && files+=(-f "$LOCAL_OVERRIDE")
  say "local: deploying origin/main @ ${sha:0:9}"
  docker compose --env-file "$LOCAL_ENV" "${files[@]}" -p docker up -d --build "${LOCAL_SERVICES[@]}"
  echo "$sha" > "$LOCAL_SHA_FILE"
  verify_local
}

# Poll until ready instead of failing on the short window where the frontend restarts.
verify_local() {
  local i web api
  for i in $(seq 1 24); do
    web="$(curl -sk -o /dev/null -w '%{http_code}' https://ifora.app 2>/dev/null || true)"
    api="$(curl -sk -o /dev/null -w '%{http_code}' https://api.ifora.app/health 2>/dev/null || true)"
    if [ "$web" = 200 ] && [ "$api" = 200 ]; then say "local: ok (ifora.app 200, api health 200)"; return; fi
    sleep 5
  done
  die "local: not healthy after 2 minutes (ifora.app $web, api $api). Try: docker logs ifora-api"
}

want() { # name: deploy when behind or unknown
  local t="$1" sha="$2"
  [ "$sha" != "$t" ]
}

case "${1:-}" in
  status) cmd_status ;;
  demo)   deploy_demo ;;
  local)  deploy_local ;;
  all)    deploy_demo; deploy_local; echo; cmd_status ;;
  "")
    t="$(target)"
    if want "$t" "$(demo_sha)";  then deploy_demo;  did=1; else say "demo already at ${t:0:9}"; fi
    if want "$t" "$(local_sha)"; then deploy_local; else say "local already at ${t:0:9}"; fi
    echo; cmd_status
    ;;
  *) sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
