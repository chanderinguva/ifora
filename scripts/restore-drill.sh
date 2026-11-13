#!/usr/bin/env bash
# Backup/restore/rollback drill in two throwaway compose projects (IFORA-21).
#
#   IFORA_DRILL_API_IMAGE=<image> [IFORA_DRILL_OLD_IMAGE=<older image>] scripts/restore-drill.sh [--keep]
#
# 1. start project ifora-drill-src, populate it THROUGH THE API (bootstrap admin, users, groups)
# 2. scripts/backup.sh it
# 3. start project ifora-drill-dst with only postgres + redis (empty database), scripts/restore.sh into it
# 4. start the API on the restored data and sign in as the admin and a seeded user
# 5. confirm a second restore into the now non-empty database is refused
# 6. with IFORA_DRILL_OLD_IMAGE (a release with an older migration head): follow the README rollback runbook on dst:
#    downgrade with the newer image, run the older image, sign in again
# Prints a timing and verification report. Touches only projects named ifora-drill-*: never the real stack, its
# ports or its volumes. IFORA_DRILL_API_IMAGE defaults to building this checkout. --keep leaves the stacks up.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$REPO/docker/docker-compose.drill.yml"
STAMP="$(date -u +%Y%m%d%H%M%S)"
SRC="ifora-drill-src"; DST="ifora-drill-dst"
KEEP=0; [ "${1:-}" = "--keep" ] && KEEP=1
OLD_IMAGE="${IFORA_DRILL_OLD_IMAGE:-}"
USER_PASSWORD="Str0ngPassw0rd!x"; ADMIN_PASSWORD="Adm1nPassw0rd!xyz"; ADMIN_EMAIL="drill-admin@example.com"; N_USERS=25

say() { echo "drill: $*"; }
die() { echo "drill: $*" >&2; exit 1; }
now() { python3 -c 'import time; print(f"{time.time():.3f}")'; }
REPORT=()
timed() { # label command...
  local label="$1" t0 t1; shift; t0="$(now)"; "$@"; t1="$(now)"
  REPORT+=("$(printf '%-46s %7.1f s' "$label" "$(python3 -c "print($t1 - $t0)")")")
}

command -v docker >/dev/null || die "docker is required"
[ -f "$COMPOSE_FILE" ] || die "missing $COMPOSE_FILE"
WORK="$(mktemp -d)"; chmod 700 "$WORK"; ENVF="$WORK/drill.env"; BACKUPS="$WORK/backups"

cleanup() {
  local rc=$?
  if [ "$KEEP" = 1 ] && [ $rc -eq 0 ]; then
    say "--keep: stacks left running (projects $SRC, $DST; secrets in $WORK). Remove with: docker compose -p $SRC -f docker/docker-compose.drill.yml --env-file $ENVF down -v"
    return
  fi
  for p in "$SRC" "$DST"; do
    case "$p" in ifora-drill-*) docker compose -p "$p" -f "$COMPOSE_FILE" --env-file "$ENVF" down -v --remove-orphans >/dev/null 2>&1 || true ;; esac
  done
  rm -rf "$WORK"
  [ $rc -eq 0 ] || echo "drill: FAILED (exit $rc); scratch stacks and secrets removed" >&2
}
trap cleanup EXIT

# ---- image ------------------------------------------------------------------------------------------------------
if [ -z "${IFORA_DRILL_API_IMAGE:-}" ]; then
  IFORA_DRILL_API_IMAGE="ifora-drill-api:$STAMP"
  say "building $IFORA_DRILL_API_IMAGE from this checkout"
  timed "build backend image from checkout" docker build -q -f "$REPO/docker/backend/Dockerfile" -t "$IFORA_DRILL_API_IMAGE" "$REPO" >/dev/null
fi
NEW_IMAGE="$IFORA_DRILL_API_IMAGE"
docker image inspect "$NEW_IMAGE" >/dev/null 2>&1 || die "image $NEW_IMAGE not found locally"
[ -z "$OLD_IMAGE" ] || docker image inspect "$OLD_IMAGE" >/dev/null 2>&1 || die "image $OLD_IMAGE not found locally"

# ---- throwaway secrets (shared by both stacks, as a restored deployment would reuse docker/.env) -------------------
fernet() { docker run --rm --entrypoint python "$NEW_IMAGE" -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"; }
( umask 077
  { echo "POSTGRES_PASSWORD=$(openssl rand -hex 24)"
    echo "SECRET_KEY=$(openssl rand -hex 32)"
    echo "ADMIN_SECRET_KEY=$(openssl rand -hex 32)"
    echo "MFA_ENCRYPTION_KEY=$(fernet)"
    echo "OIDC_KEY_ENCRYPTION_KEY=$(fernet)"
    echo "RECIPE_ENCRYPTION_KEY=$(fernet)"; } > "$ENVF" )
ADMIN_SECRET="$(grep '^ADMIN_SECRET_KEY=' "$ENVF" | cut -d= -f2)"

dc() { local p="$1"; shift; IFORA_DRILL_API_IMAGE="${API_IMAGE:-$NEW_IMAGE}" docker compose -p "$p" -f "$COMPOSE_FILE" --env-file "$ENVF" "$@"; }
cid() { dc "$1" ps -q "$2"; }
wait_healthy() { # project service
  local c n=120 s; c="$(cid "$1" "$2")"
  while [ $n -gt 0 ]; do
    s="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$c" 2>/dev/null || echo missing)"
    [ "$s" = healthy ] && return 0
    sleep 2; n=$((n - 1))
  done
  die "$1/$2 not healthy (last: $s). Try: docker logs $c"
}
start_api() { dc "$1" up -d "${@:2}" >/dev/null 2>&1; wait_healthy "$1" backend-api; } # project [compose up args]
downgrade_to() { docker exec "$1" alembic -c backend/alembic.ini downgrade "$2" >/dev/null 2>&1; }
env_api_old() { API_IMAGE="$OLD_IMAGE" "$@"; } # run a function with compose pointed at the older image
client() { docker exec -i "$(cid "$1" backend-api)" python - "${@:2}" < "$REPO/scripts/restore_drill_client.py"; }
counts() { IFORA_PG_CONTAINER="$(cid "$1" postgres)" bash -c ". '$REPO/scripts/backup-lib.sh'; echo version=\$(alembic_version); table_counts"; }

# ---- 1. source stack, populated through the API ---------------------------------------------------------------
say "source stack ($SRC)"
timed "source: start stack + run migrations" start_api "$SRC"
client "$SRC" bootstrap "$ADMIN_EMAIL" "$ADMIN_PASSWORD" "$ADMIN_SECRET"
timed "source: seed $N_USERS users + 3 groups via API" client "$SRC" seed "$ADMIN_EMAIL" "$ADMIN_PASSWORD" "$N_USERS" "$USER_PASSWORD"
SRC_COUNTS="$(counts "$SRC")"; say "source: ${SRC_COUNTS//$'\n'/ }"

# ---- 2. backup --------------------------------------------------------------------------------------------------
timed "backup (scripts/backup.sh)" env IFORA_PG_CONTAINER="$(cid "$SRC" postgres)" IFORA_BACKUP_DIR="$BACKUPS" "$REPO/scripts/backup.sh" >"$WORK/backup.out"
DUMP="$(ls "$BACKUPS"/ifora-*.dump)"; DUMP_BYTES="$(wc -c < "$DUMP" | tr -d ' ')"

# ---- 3. empty destination, restore ----------------------------------------------------------------------------------
say "destination stack ($DST): postgres and redis only, empty database"
dc "$DST" up -d postgres redis >/dev/null 2>&1; wait_healthy "$DST" postgres
timed "restore (scripts/restore.sh)" env IFORA_PG_CONTAINER="$(cid "$DST" postgres)" "$REPO/scripts/restore.sh" "$DUMP" >"$WORK/restore.out"
cat "$WORK/restore.out" | grep -E "matches|MISMATCH|restored" | sed 's/^/  /'

# ---- 4. application on the restored data ---------------------------------------------------------------------
timed "destination: start API on restored data" start_api "$DST" backend-api
client "$DST" login "$ADMIN_EMAIL" "$ADMIN_PASSWORD"
client "$DST" login "drill0@example.com" "$USER_PASSWORD"
DST_COUNTS="$(counts "$DST")"
[ "$SRC_COUNTS" = "$DST_COUNTS" ] || die "counts differ after restore:$(printf '\n--- source\n%s\n--- destination\n%s' "$SRC_COUNTS" "$DST_COUNTS")"
say "destination counts equal the source"

# ---- 5. refusal on a non-empty target ----------------------------------------------------------------------------
if IFORA_PG_CONTAINER="$(cid "$DST" postgres)" "$REPO/scripts/restore.sh" "$DUMP" >"$WORK/refuse.out" 2>&1; then die "second restore was NOT refused"; fi
grep -q "already has" "$WORK/refuse.out" || die "second restore failed for an unexpected reason: $(cat "$WORK/refuse.out")"
say "second restore into the non-empty database refused (as designed)"

# ---- 6. rollback to an older release (README runbook) ----------------------------------------------------------
if [ -n "$OLD_IMAGE" ]; then
  OLD_HEAD="$(docker run --rm --entrypoint alembic "$OLD_IMAGE" -c backend/alembic.ini heads | awk '{print $1}')"
  API_C="$(cid "$DST" backend-api)"
  CUR="$(docker exec "$API_C" alembic -c backend/alembic.ini current 2>/dev/null | awk 'NF{print $1; exit}')"
  say "rollback: database at $CUR, older image expects $OLD_HEAD"
  [ "$CUR" != "$OLD_HEAD" ] || say "note: both images share head $OLD_HEAD; nothing to downgrade"
  timed "rollback: downgrade with the newer image" downgrade_to "$API_C" "$OLD_HEAD"
  timed "rollback: start older image, wait healthy" env_api_old start_api "$DST" --no-deps --force-recreate backend-api
  client "$DST" login "drill0@example.com" "$USER_PASSWORD"
  AFTER="$(docker exec "$(cid "$DST" backend-api)" alembic -c backend/alembic.ini current 2>/dev/null | awk 'NF{print $1; exit}')"
  [ "$AFTER" = "$OLD_HEAD" ] || die "after rollback the database is at $AFTER, expected $OLD_HEAD"
  say "rollback ok: older image running at $AFTER and the seeded user still signs in"
fi

# ---- report ---------------------------------------------------------------------------------------------------------
echo
echo "== Restore drill report =="
echo "image (new): $NEW_IMAGE"; [ -z "$OLD_IMAGE" ] || echo "image (old): $OLD_IMAGE"
echo "dump: $DUMP_BYTES bytes; ${SRC_COUNTS//$'\n'/ }"
printf '%s\n' "${REPORT[@]}"
echo "verified: counts equal; admin + seeded user sign in on restored data; second restore refused${OLD_IMAGE:+; rollback to older release}"
