#!/usr/bin/env bash
# Build, push and deploy helper for the local Drone CI pipeline (.drone.yml).
#
#   scripts/ci-deploy.sh build  [sha]          build ghcr.io/<owner>/ifora-* images for <sha> and push them
#   scripts/ci-deploy.sh deploy demo  [sha]    roll the demo stack (compose project ifora-demo) onto those images
#   scripts/ci-deploy.sh deploy local [sha]    roll the dev/prod stack (compose project ifora) onto those images
#
# <sha> defaults to $DRONE_COMMIT_SHA, then to HEAD. Images are tagged with its first 12 characters:
#   ifora-api:<tag>  ifora-recipes-worker:<tag>   same image (one backend Dockerfile), two names
#   ifora-frontend:<tag>-demo / <tag>-local       NEXT_PUBLIC_API_URL is baked in at build time, so one image per site
#
# It reuses the stacks that scripts/deploy.sh already manages: same project names (never any other), same env files
# outside the repo, same deployed-sha files. Only the image source changes (pre-built instead of built on the spot).
# Rollback = run `deploy <env> <older-sha>`; a missing image is pulled from GHCR first.
#
# Inside Drone the host's $HOME is mounted at the same path, so bind mounts in the compose files resolve on the host.
set -euo pipefail

REGISTRY="${REGISTRY:-ghcr.io}"
HOME_DIR="${HOME:?}"
DEMO_HOME="${DEMO_HOME:-$HOME_DIR/ifora-demo}"
LOCAL_ENV="${LOCAL_ENV:-$HOME_DIR/Development/ifora/docker/.env}"
LOCAL_OVERRIDE="${LOCAL_OVERRIDE:-$HOME_DIR/Development/ifora-app-local/ifora-app.yml}"
LOCAL_SHA_FILE="${LOCAL_SHA_FILE:-$HOME_DIR/.ifora-local-deployed-sha}"
DEMO_API_URL="${DEMO_API_URL:-https://demo.ifora.app}"
LOCAL_API_URL="${LOCAL_API_URL:-https://api.ifora.app}"
LOCAL_FRONTEND_TARGET="${LOCAL_FRONTEND_TARGET:-dev}" # what docker/.env gives the local stack today
LOCAL_SERVICES=(backend-api frontend recipes-worker)  # the edge is a stock image; the rest are data stores

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
die() { echo "ci-deploy: $*" >&2; exit 1; }
say() { echo "ci-deploy: $*"; }

OWNER="$(printf %s "${DRONE_REPO_OWNER:-${IMAGE_OWNER:-}}" | tr '[:upper:]' '[:lower:]')" # GHCR names must be lowercase
[ -n "$OWNER" ] || die "set DRONE_REPO_OWNER (Drone does) or IMAGE_OWNER"

images_for() { # sha -> sets IMG_API IMG_WORKER IMG_FE_DEMO IMG_FE_LOCAL
  SHA="${1:-${DRONE_COMMIT_SHA:-$(git -C "$REPO" rev-parse HEAD)}}"
  TAG="${SHA:0:12}"
  IMG_API="$REGISTRY/$OWNER/ifora-api:$TAG"
  IMG_WORKER="$REGISTRY/$OWNER/ifora-recipes-worker:$TAG"
  IMG_FE_DEMO="$REGISTRY/$OWNER/ifora-frontend:$TAG-demo"
  IMG_FE_LOCAL="$REGISTRY/$OWNER/ifora-frontend:$TAG-local"
}

cmd_build() {
  images_for "${1:-}"
  : "${GHCR_USER:?GHCR_USER (GitHub login) is required}" "${GHCR_TOKEN:?GHCR_TOKEN (PAT with write:packages) is required}"
  printf %s "$GHCR_TOKEN" | docker login "$REGISTRY" -u "$GHCR_USER" --password-stdin
  cd "$REPO"
  say "building $TAG"
  docker build -f docker/backend/Dockerfile -t "$IMG_API" -t "$IMG_WORKER" .
  docker build -f docker/frontend/Dockerfile --target prod \
    --build-arg "NEXT_PUBLIC_API_URL=$DEMO_API_URL" -t "$IMG_FE_DEMO" .
  docker build -f docker/frontend/Dockerfile --target "$LOCAL_FRONTEND_TARGET" \
    --build-arg "NEXT_PUBLIC_API_URL=$LOCAL_API_URL" -t "$IMG_FE_LOCAL" .
  for i in "$IMG_API" "$IMG_WORKER" "$IMG_FE_DEMO" "$IMG_FE_LOCAL"; do docker push "$i"; done
  docker logout "$REGISTRY" >/dev/null
  say "pushed $TAG"
}

ensure_image() { docker image inspect "$1" >/dev/null 2>&1 || { say "pulling $1"; docker pull "$1"; }; }

export_tree() { # dest: the commit's files only, no .git, no working-tree changes
  mkdir -p "$1"
  git -C "$REPO" config --global --add safe.directory '*' 2>/dev/null || true
  git -C "$REPO" archive "$SHA" | tar -x -C "$1"
}

wait_healthy() { # container [seconds]
  local c="$1" n="${2:-180}" s
  while [ "$n" -gt 0 ]; do
    s="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$c" 2>/dev/null || echo missing)"
    case "$s" in healthy|running) say "$c: $s"; return 0 ;; esac
    sleep 5; n=$((n - 5))
  done
  die "$c is not healthy (last state: $s). Try: docker logs $c"
}

wait_http() { # container url [seconds]: probe from inside the network (the host's /etc/hosts is not ours)
  local c="$1" url="$2" n="${3:-180}"
  while [ "$n" -gt 0 ]; do
    docker exec "$c" wget -qO /dev/null "$url" 2>/dev/null && { say "$c answers $url"; return 0; }
    sleep 5; n=$((n - 5))
  done
  die "$c did not answer $url. Try: docker logs $c"
}

deploy_demo() {
  images_for "${1:-}"
  local env_file="$DEMO_HOME/.env.demo" src="$DEMO_HOME/src-ci" # not src/: that one is a git worktree owned by demo.sh
  [ -f "$env_file" ] || die "missing $env_file (run: scripts/demo.sh init)"
  ensure_image "$IMG_API"; ensure_image "$IMG_WORKER"; ensure_image "$IMG_FE_DEMO"
  say "demo: deploying ${SHA:0:9}"
  export_tree "$src"
  IFORA_API_IMAGE="$IMG_API" IFORA_WORKER_IMAGE="$IMG_WORKER" IFORA_FRONTEND_IMAGE="$IMG_FE_DEMO" \
    docker compose -p ifora-demo --project-directory "$src/docker" \
      -f "$src/docker/docker-compose.yml" -f "$src/docker/docker-compose.prod.yml" \
      -f "$src/docker/docker-compose.demo.yml" -f "$src/docker/docker-compose.ci.yml" \
      --env-file "$env_file" up -d --no-build --remove-orphans
  # The Caddyfile is bind-mounted and re-extracted on every deploy (new inode), so recreate the edge to pick it up.
  IFORA_API_IMAGE="$IMG_API" IFORA_WORKER_IMAGE="$IMG_WORKER" IFORA_FRONTEND_IMAGE="$IMG_FE_DEMO" \
    docker compose -p ifora-demo --project-directory "$src/docker" \
      -f "$src/docker/docker-compose.yml" -f "$src/docker/docker-compose.prod.yml" \
      -f "$src/docker/docker-compose.demo.yml" -f "$src/docker/docker-compose.ci.yml" \
      --env-file "$env_file" up -d --no-build --no-deps --force-recreate edge
  wait_healthy ifora-demo-api
  wait_healthy ifora-demo-recipes-worker
  wait_http ifora-demo-frontend http://127.0.0.1:3000/login
  wait_http ifora-demo-edge http://127.0.0.1/
  echo "$SHA" > "$DEMO_HOME/deployed-sha"
  say "demo: ok at ${SHA:0:9}"
}

deploy_local() {
  images_for "${1:-}"
  [ -f "$LOCAL_ENV" ] || die "missing $LOCAL_ENV (set LOCAL_ENV)"
  ensure_image "$IMG_API"; ensure_image "$IMG_WORKER"; ensure_image "$IMG_FE_LOCAL"
  local src files; src="$(mktemp -d)"; trap 'rm -rf "$src"' EXIT
  export_tree "$src"
  files=(-f "$src/docker/docker-compose.yml")
  [ -f "$LOCAL_OVERRIDE" ] && files+=(-f "$LOCAL_OVERRIDE")
  files+=(-f "$src/docker/docker-compose.ci.yml")
  say "local: deploying ${SHA:0:9}"
  IFORA_API_IMAGE="$IMG_API" IFORA_WORKER_IMAGE="$IMG_WORKER" IFORA_FRONTEND_IMAGE="$IMG_FE_LOCAL" \
    docker compose --env-file "$LOCAL_ENV" --project-directory "$src/docker" "${files[@]}" -p ifora \
      up -d --no-build "${LOCAL_SERVICES[@]}"
  wait_healthy ifora-api
  wait_healthy ifora-recipes-worker
  wait_http ifora-frontend http://127.0.0.1:3000/login
  echo "$SHA" > "$LOCAL_SHA_FILE"
  say "local: ok at ${SHA:0:9}"
}

case "${1:-}" in
  build)  shift; cmd_build "$@" ;;
  deploy)
    shift
    case "${1:-}" in
      demo)  shift; deploy_demo "$@" ;;
      local) shift; deploy_local "$@" ;;
      *) die "usage: ci-deploy.sh deploy demo|local [sha]" ;;
    esac ;;
  *) sed -n '2,15p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
