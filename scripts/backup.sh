#!/usr/bin/env bash
# Back up the IdentityForge/ifora PostgreSQL database (IFORA-21).
#
#   scripts/backup.sh [--dir DIR]
#
# Writes DIR/ifora-<UTC timestamp>.dump (pg_dump custom format) and a matching .manifest (sha256, migration version,
# row counts) with mode 600. DIR defaults to $IFORA_BACKUP_DIR or ~/ifora-backups and must be OUTSIDE this checkout:
# backups hold password hashes, TOTP secrets and PII and must never be committed.
#
# Environment: IFORA_PG_CONTAINER (default ifora-postgres), IFORA_PG_USER (ifora), IFORA_PG_DB (ifora).
# NOT in the backup: Redis (sessions and rate-limit counters; users just sign in again) and every secret in
# docker/.env. Without the encryption keys a restored database cannot decrypt MFA, OIDC-signing, SWA and recipe secrets.
# See README "Backup, restore and rollback".
set -euo pipefail
umask 077

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
# shellcheck source=scripts/backup-lib.sh
. "$HERE/backup-lib.sh"

DIR="${IFORA_BACKUP_DIR:-$HOME/ifora-backups}"
while [ $# -gt 0 ]; do
  case "$1" in
    --dir) DIR="${2:?--dir needs a path}"; shift 2 ;;
    -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown argument: $1 (try --help)" ;;
  esac
done

need_container
mkdir -p "$DIR"
DIR="$(cd "$DIR" && pwd -P)"
case "$DIR/" in "$REPO"/*) die "refusing to write backups inside the checkout ($DIR): they contain secrets and PII" ;; esac

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BASE="$DIR/ifora-$STAMP"
[ ! -e "$BASE.dump" ] || die "$BASE.dump already exists; wait a second and retry"
PARTIAL="$BASE.dump.partial"
trap 'rm -f "$PARTIAL"' EXIT

VERSION="$(alembic_version)"
BEFORE="$(table_counts)"
say "dumping $PG_DB from $PG_CONTAINER (migration $VERSION)"
docker exec -i "$PG_CONTAINER" pg_dump -U "$PG_USER" -d "$PG_DB" -Fc --no-owner --no-acl > "$PARTIAL"
AFTER="$(table_counts)"

# A dump that cannot be listed is not a backup: fail before it gets a final name.
docker exec -i "$PG_CONTAINER" pg_restore --list < "$PARTIAL" >/dev/null || die "dump failed validation; nothing written"
[ -s "$PARTIAL" ] || die "dump is empty; nothing written"

STABLE=true
[ "$BEFORE" = "$AFTER" ] || { STABLE=false; say "WARNING: row counts changed while dumping (live traffic); restore verification will only warn"; }

mv "$PARTIAL" "$BASE.dump"
chmod 600 "$BASE.dump"
{
  echo "created_utc=$STAMP"
  echo "pg_server=$(psql_q 'SHOW server_version')"
  echo "alembic_version=$VERSION"
  echo "dump_file=$(basename "$BASE.dump")"
  echo "dump_bytes=$(wc -c < "$BASE.dump" | tr -d ' ')"
  echo "dump_sha256=$(sha256_of "$BASE.dump")"
  echo "counts_stable=$STABLE"
  echo "$AFTER"
} > "$BASE.manifest"
chmod 600 "$BASE.manifest"
trap - EXIT

say "wrote $BASE.dump ($(wc -c < "$BASE.dump" | tr -d ' ') bytes) and $BASE.manifest"
cat <<'NOTE'

Also back up, separately and encrypted: configuration and secrets, which are NOT in the dump (names only; values stay in docker/.env):
NOTE
if [ -f "$REPO/docker/.env.example" ]; then
  grep -oE '^#?[A-Z][A-Z0-9_]+=' "$REPO/docker/.env.example" | tr -d '#=' | sort -u | sed 's/^/  - /'
fi
cat <<'NOTE'
  - the OpenBao data and unseal material, if you use docker-compose.openbao.yml
Redis holds only sessions and rate-limit counters; it is not backed up. Encrypt the files above before they leave
this machine (age or gpg), and keep the encryption keys apart from the dump.
NOTE
