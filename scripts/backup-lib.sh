# Shared by scripts/backup.sh and scripts/restore.sh (IFORA-21). Sourced, not executed.
# Talks to PostgreSQL through `docker exec` on the postgres container, so no client tools or passwords are needed on
# the host (the postgres image trusts local socket connections inside the container).

PG_CONTAINER="${IFORA_PG_CONTAINER:-ifora-postgres}"
PG_USER="${IFORA_PG_USER:-ifora}"
PG_DB="${IFORA_PG_DB:-ifora}"

# Entities whose counts must survive a restore. Deliberately excludes sessions and audit_events: they change while
# the app is running, so a live backup could never match.
COUNT_TABLES="tenants users groups applications application_assignments"

die() { echo "$(basename "$0"): $*" >&2; exit 1; }
say() { echo "$(basename "$0"): $*"; }

psql_q() { # sql -> unaligned, tuples-only output
  docker exec -i "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -X -v ON_ERROR_STOP=1 -Atc "$1"
}

need_container() {
  command -v docker >/dev/null 2>&1 || die "docker is not installed or not on PATH"
  [ "$(docker inspect -f '{{.State.Running}}' "$PG_CONTAINER" 2>/dev/null || true)" = true ] \
    || die "postgres container '$PG_CONTAINER' is not running (set IFORA_PG_CONTAINER)"
}

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

alembic_version() { psql_q "SELECT version_num FROM alembic_version" 2>/dev/null || echo none; }

# Prints "count.<table>=<n>" lines; a table that does not exist (older schema) is reported as "absent".
table_counts() {
  local t n
  for t in $COUNT_TABLES; do
    if [ "$(psql_q "SELECT to_regclass('public.$t') IS NOT NULL")" = t ]; then
      n="$(psql_q "SELECT count(*) FROM public.$t")"
    else
      n=absent
    fi
    echo "count.$t=$n"
  done
}
