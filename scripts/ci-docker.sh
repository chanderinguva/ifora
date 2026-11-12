#!/usr/bin/env bash
# Container-only entrypoint; never use the mounted Mac credential store.
set -euo pipefail
command -v docker >/dev/null
: "${GHCR_USER:?set ghcr_user in Drone}" "${GHCR_TOKEN:?set ghcr_token in Drone}"
CI_DOCKER_CONFIG="$(mktemp -d /tmp/ifora-docker-config.XXXXXX)"
chmod 700 "$CI_DOCKER_CONFIG"
cleanup() { rm -rf "$CI_DOCKER_CONFIG"; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
export DOCKER_CONFIG="$CI_DOCKER_CONFIG"
# Do not copy credsStore, currentContext, or any host registry credentials.
printf '{"auths":{}}\n' > "$DOCKER_CONFIG/config.json"
chmod 600 "$DOCKER_CONFIG/config.json"
printf %s "$GHCR_TOKEN" | docker login "${REGISTRY:-ghcr.io}" -u "$GHCR_USER" --password-stdin
if [ "${1:-}" = preflight ]; then
  docker version >/dev/null
  docker compose version
  docker buildx version
  test -r "${DEMO_HOME:-$HOME/ifora-demo}/.env.demo" || {
    echo "Missing demo environment file; cannot deploy." >&2; exit 1;
  }
  test -r "${LOCAL_ENV:-$HOME/Development/ifora/docker/.env}" || {
    echo "Missing local environment file; cannot deploy." >&2; exit 1;
  }
  echo "CI preflight passed: registry login, Docker, Compose, Buildx and deployment env files."
else
  bash "$(dirname "$0")/ci-deploy.sh" "$@"
fi
