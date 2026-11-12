#!/bin/sh
# Preserve the command's status and record phase timing for Slack, without credentials.
set -u
phase=$1
shift
case "$phase" in
  preflight|prepare-test-images|test-backend|check-frontend|build-and-push|deploy-demo|deploy-local) ;;
  *) echo "Unknown CI phase" >&2; exit 2 ;;
esac
mkdir -p .ci/results
started=$(date +%s)
printf '{"status":"running","seconds":0}\n' > ".ci/results/$phase.json"
finish() {
  code=$?
  trap - EXIT
  ended=$(date +%s)
  state=success
  [ "$code" -eq 0 ] || state=failure
  printf '{"status":"%s","seconds":%s}\n' "$state" "$((ended-started))" > ".ci/results/$phase.json"
  exit "$code"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
"$@"
