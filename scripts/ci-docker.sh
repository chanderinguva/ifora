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
  # Login alone does not prove package write access. Publish a tiny, non-release
  # tag to each exact package before the test suite. No application image is run.
  CI_IMAGE_OWNER="$(printf %s "${DRONE_REPO_OWNER:-${IMAGE_OWNER:-}}" | tr '[:upper:]' '[:lower:]')"
  : "${CI_IMAGE_OWNER:?set DRONE_REPO_OWNER or IMAGE_OWNER}"
  CI_PROBE_CONTEXT="$CI_DOCKER_CONFIG/probe"
  mkdir "$CI_PROBE_CONTEXT"
  printf 'FROM scratch\nLABEL io.ifora.ci.permission-probe="true"\n' > "$CI_PROBE_CONTEXT/Dockerfile"
  for package in ifora-api ifora-recipes-worker ifora-frontend; do
    CI_PROBE_IMAGE="${REGISTRY:-ghcr.io}/$CI_IMAGE_OWNER/$package:ci-permission-check"
    echo "Checking package push access: $CI_PROBE_IMAGE"
    docker build --quiet -t "$CI_PROBE_IMAGE" "$CI_PROBE_CONTEXT" >/dev/null
    if ! docker push "$CI_PROBE_IMAGE"; then
      echo "Cannot publish $package. Check Drone ghcr_token: classic PAT with write:packages and package write access. Tests have not started." >&2
      exit 1
    fi
  done
  echo "CI preflight passed: registry push access for all three packages, Docker tooling and deployment env files."
else
  bash "$(dirname "$0")/ci-deploy.sh" "$@"
fi
