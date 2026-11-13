#!/usr/bin/env bash
# Restore a scripts/backup.sh dump into a PostgreSQL container (IFORA-21).
#
#   scripts/restore.sh DUMP [--force] [--skip-checksum]
#
# Refuses to touch a target that already has tables unless --force (which replaces the dumped objects). The restore
# runs as ONE transaction, so an interrupted or corrupt restore leaves the target exactly as it was. Before restoring
# it checks the dump against its .manifest sha256; afterwards it compares the migration version and row counts.
#
# Stop the application containers first so nothing writes during the restore. Point it at a scratch stack to rehearse:
#   IFORA_PG_CONTAINER=<scratch-postgres> scripts/restore.sh ~/ifora-backups/ifora-<stamp>.dump
# Exit codes: 0 restored and verified, 1 refused or failed (target unchanged), 3 restored but verification differs.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/backup-lib.sh
. "$HERE/backup-lib.sh"

DUMP="" FORCE=0 SKIP_SUM=0
while [ $# -gt 0 ]; do
  case "$1" in
    --force) FORCE=1; shift ;;
    --skip-checksum) SKIP_SUM=1; shift ;;
    -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) die "unknown argument: $1 (try --help)" ;;
    *) [ -z "$DUMP" ] || die "only one dump file allowed"; DUMP="$1"; shift ;;
  esac
done
[ -n "$DUMP" ] || die "usage: restore.sh DUMP [--force] [--skip-checksum]"
[ -f "$DUMP" ] || die "no such file: $DUMP"
MANIFEST="${DUMP%.dump}.manifest"

mget() { grep -m1 "^$1=" "$MANIFEST" | cut -d= -f2-; }

need_container

# 1. Integrity: the dump must match the checksum recorded when it was taken.
if [ -f "$MANIFEST" ]; then
  [ "$(sha256_of "$DUMP")" = "$(mget dump_sha256)" ] || die "checksum mismatch: $DUMP differs from its manifest; refusing"
  say "checksum ok"
elif [ "$SKIP_SUM" = 1 ]; then
  say "WARNING: no manifest, checksum not verified"
else
  die "no manifest next to the dump ($MANIFEST); pass --skip-checksum only if you trust this file"
fi
docker exec -i "$PG_CONTAINER" pg_restore --list < "$DUMP" >/dev/null || die "not a readable pg_dump custom-format file; target untouched"

# 2. Safety: never overwrite an existing database by accident.
TABLES="$(psql_q "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")"
CLEAN=()
if [ "$TABLES" != 0 ]; then
  [ "$FORCE" = 1 ] || die "target database '$PG_DB' in '$PG_CONTAINER' already has $TABLES tables; refusing. Use --force to replace them (take a backup first)."
  CLEAN=(--clean --if-exists)
  say "WARNING: --force: replacing existing objects in $PG_DB"
fi

# 3. Restore in a single transaction: any error rolls everything back.
say "restoring $(basename "$DUMP") into $PG_DB on $PG_CONTAINER"
if ! docker exec -i "$PG_CONTAINER" pg_restore -U "$PG_USER" -d "$PG_DB" --single-transaction --exit-on-error \
      --no-owner --no-acl "${CLEAN[@]+"${CLEAN[@]}"}" < "$DUMP"; then
  die "restore failed and was rolled back; target is unchanged"
fi

# 4. Verify against the manifest.
status=0
if [ -f "$MANIFEST" ]; then
  want_ver="$(mget alembic_version)"; got_ver="$(alembic_version)"
  if [ "$want_ver" = "$got_ver" ]; then say "migration version $got_ver matches"; else say "MISMATCH: migration version is $got_ver, backup had $want_ver"; status=3; fi
  stable="$(mget counts_stable)"
  for t in $COUNT_TABLES; do
    want="$(mget "count.$t")"; got="$(table_counts | grep "^count.$t=" | cut -d= -f2)"
    if [ "$want" = "$got" ]; then
      say "$t: $got rows (matches)"
    elif [ "$stable" = true ]; then
      say "MISMATCH: $t has $got rows, backup had $want"; status=3
    else
      say "note: $t has $got rows, backup recorded $want (backup was taken under live traffic)"
    fi
  done
fi
if [ "$status" = 0 ]; then
  say "restored and verified"
else
  say "restored, but verification differs (see above)"
fi
echo "Next: start the application so it applies any newer migrations, and sign in to confirm. Restore the secrets from docker/.env separately."
exit "$status"
