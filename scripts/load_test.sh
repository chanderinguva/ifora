#!/usr/bin/env bash
# Run the k6 load scripts in tests/load against a stack you point it at (IFORA-59). Never against a shared or public host.
#
#   BASE_URL=http://localhost:8310 ADMIN_EMAIL=... ADMIN_PASSWORD=... make test-load
#   Optional: SCRIPTS="auth_flow userinfo"  VUS=20  RAMP=30s  DURATION=2m  USERS=20  P95_MS=...  MAX_ERROR_RATE=0.01
set -euo pipefail
cd "$(dirname "$0")/.."

command -v docker >/dev/null || { echo "docker is required: install Docker Desktop (k6 runs from a pinned image, nothing else to install)"; exit 2; }
BASE_URL="${BASE_URL:-http://localhost:8310}"
case "$BASE_URL" in
  http://localhost:*|http://127.0.0.1:*) ;;
  *) [ "${ALLOW_REMOTE:-}" = "1" ] || { echo "refusing to load-test $BASE_URL: only a local, disposable stack by default (ALLOW_REMOTE=1 overrides, on a stack you own)"; exit 2; } ;;
esac
SCRIPTS="${SCRIPTS:-auth_flow refresh userinfo}"
USERS="${USERS:-20}"
IMAGE=ifora-load-k6:pinned

docker build -q -t "$IMAGE" -f docker/load/k6.Dockerfile docker/load >/dev/null
mkdir -p tests/load/results; rm -f tests/load/results/*.json
trap 'python3 tests/load/seed.py down || echo "CLEANUP FAILED: run python3 tests/load/seed.py down" >&2' EXIT
BASE_URL="$BASE_URL" python3 tests/load/seed.py up "$USERS"

# The container reaches the host's stack through host.docker.internal.
K6_BASE="${BASE_URL/localhost/host.docker.internal}"; K6_BASE="${K6_BASE/127.0.0.1/host.docker.internal}"
rc=0
for s in $SCRIPTS; do
  echo; echo "=== k6 $s (VUS=${VUS:-10} RAMP=${RAMP:-20s} DURATION=${DURATION:-60s} users=$USERS) ==="
  docker run --rm --add-host host.docker.internal:host-gateway -v "$PWD/tests/load:/work" -w /work \
    -e BASE_URL="$K6_BASE" -e VUS -e RAMP -e DURATION -e P95_MS -e MAX_ERROR_RATE -e THINK_SECONDS \
    "$IMAGE" run --quiet "/work/$s.js" || rc=1
done
python3 tests/load/report.py
exit $rc
