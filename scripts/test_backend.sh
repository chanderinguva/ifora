#!/usr/bin/env bash
# Run the backend test suite in a THROWAWAY container with THIS checkout mounted.
# Uses the image, network and env of the running `ifora-api` container (it only supplies the toolchain
# and service endpoints; its baked-in code is stale and is NOT what gets tested).
# Usage: scripts/test_backend.sh [pytest args...]     e.g. scripts/test_backend.sh tests/test_foo.py -x
# Note: fixtures create a database on the shared dev Postgres. Do not point this at production.
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)/backend"
API="${IFORA_API_CONTAINER:-ifora-api}"

if ! docker inspect "$API" >/dev/null 2>&1; then
  echo "MISSING: container '$API' is not running; start the dev stack (docker compose up -d) first." >&2
  exit 127
fi

IMAGE="$(docker inspect "$API" --format '{{.Config.Image}}')"
NETWORK="$(docker inspect "$API" --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' | awk '{print $1}')"

ENVFILE="$(mktemp)"
trap 'rm -f "$ENVFILE"' EXIT
chmod 600 "$ENVFILE"
# Drop dev-stack settings the tests assume are unset (their app defaults apply): the WebAuthn relying party/origins
# and OIDC login/logout UI URLs (the dev stack uses ifora.app; tests expect localhost) and the recipe encryption key (tests cover the no-key paths).
docker inspect "$API" --format '{{range .Config.Env}}{{println .}}{{end}}' \
  | grep -v '^$' | grep -Ev '^(WEBAUTHN_RP_ID|WEBAUTHN_ORIGINS|RECIPE_ENCRYPTION_KEY|OIDC_LOGIN_UI_URL|OIDC_LOGOUT_UI_URL)=' > "$ENVFILE"

ARGS=("$@")
if [ ${#ARGS[@]} -eq 0 ]; then ARGS=(); fi

# --entrypoint sh skips the image's migration entrypoint. The two -e overrides are required because the dev stack
# uses https://ifora.app with Secure cookies, which makes every login-then-request test return 401 over plain HTTP,
# and CORS_ORIGINS must allow the tests' Origin (http://localhost:3000) or every login returns 403.
docker run --rm --entrypoint sh --network "$NETWORK" --env-file "$ENVFILE" \
  -e SESSION_COOKIE_SECURE=false -e PUBLIC_APP_URL=http://localhost:3000 -e 'CORS_ORIGINS=["http://localhost:3000"]' \
  -v "$SRC":/app/backend -w /app/backend "$IMAGE" \
  -c 'pip install -q --require-hashes -r requirements-dev.txt && python -m pytest -q -p no:cacheprovider "$@"' sh "${ARGS[@]+"${ARGS[@]}"}"
