#!/usr/bin/env bash
# Operate the invite-only demo environment (https://demo.ifora.app), a compose project separate from dev/prod.
#
#   scripts/demo.sh init             create $DEMO_HOME/.env.demo with freshly generated secrets (never overwrites)
#   scripts/demo.sh deploy           build and start the latest origin/main (what "new features reach the demo" means)
#   scripts/demo.sh bootstrap-admin  create the first administrator (prints a generated password once)
#   scripts/demo.sh smoke            check the stack and the edge routing from inside the network
#   scripts/demo.sh status | logs [service] | down
#   scripts/demo.sh reset --yes      DESTROY the demo database and volumes, redeploy, re-create the admin
#
# The demo never builds from your working tree: deploy checks out origin/main into $DEMO_HOME/src and builds there.
# Secrets live in $DEMO_HOME/.env.demo, outside the repository. The project name is fixed to "ifora-demo", so no
# command here can touch the dev/prod stack ("docker").
set -euo pipefail

DEMO_HOME="${DEMO_HOME:-$HOME/ifora-demo}"
ENV_FILE="$DEMO_HOME/.env.demo"
SRC="$DEMO_HOME/src"
PROJECT="ifora-demo"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

die() { echo "demo: $*" >&2; exit 1; }
fernet() { python3 -c 'import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())'; }
token() { python3 -c 'import secrets;print(secrets.token_urlsafe(48))'; }

compose() {
  [ -f "$ENV_FILE" ] || die "missing $ENV_FILE (run: scripts/demo.sh init)"
  [ -d "$SRC/docker" ] || die "missing $SRC (run: scripts/demo.sh deploy)"
  docker compose -p "$PROJECT" --project-directory "$SRC/docker" \
    -f "$SRC/docker/docker-compose.yml" -f "$SRC/docker/docker-compose.prod.yml" -f "$SRC/docker/docker-compose.demo.yml" \
    --env-file "$ENV_FILE" "$@"
}

cmd_init() {
  [ ! -e "$ENV_FILE" ] || die "$ENV_FILE already exists; refusing to overwrite (rotating secrets would orphan the demo data)"
  mkdir -p "$DEMO_HOME"
  umask 077
  cat > "$ENV_FILE" <<EOF
# Demo environment (https://demo.ifora.app). Generated $(date -u +%Y-%m-%dT%H:%M:%SZ). Not shared with docker/.env.
PUBLIC_APP_URL=https://demo.ifora.app
OIDC_ISSUER=https://demo.ifora.app
NEXT_PUBLIC_API_URL=https://demo.ifora.app
CORS_ORIGINS=["https://demo.ifora.app"]
FORWARDED_ALLOW_IPS=172.31.77.2
WEBAUTHN_RP_ID=demo.ifora.app
WEBAUTHN_ORIGINS=["https://demo.ifora.app"]
FRONTEND_TARGET=prod
# Sign in through Cloudflare Access (team domain + the Access application's AUD tag, from Zero Trust > Access):
ACCESS_SSO_ENABLED=false
ACCESS_TEAM_DOMAIN=
ACCESS_AUD=
ACCESS_SSO_AUTO_CREATE=true
# Invite by email (all four to switch on): a Cloudflare token limited to Access: Apps and Policies: Edit.
ACCESS_ALLOWLIST_TOKEN=
ACCESS_ALLOWLIST_ACCOUNT_ID=
ACCESS_ALLOWLIST_APP_ID=
ACCESS_ALLOWLIST_POLICY_ID=
# Outbound email via Cloudflare Email Service (SMTP). Fill SMTP_PASSWORD (token: Email Sending: Edit) and SMTP_FROM.
SMTP_HOST=
SMTP_PORT=465
SMTP_IMPLICIT_TLS=true
SMTP_USERNAME=api_token
SMTP_PASSWORD=
SMTP_FROM=
ADMIN_MFA_REQUIRED=true
# No real email from the demo: SMTP_* stays unset.

# Zero Trust > Networks > Tunnels > your tunnel > token
CLOUDFLARE_TUNNEL_TOKEN=

POSTGRES_PASSWORD=$(token)
SECRET_KEY=$(token)
ADMIN_SECRET_KEY=$(token)
METRICS_TOKEN=$(token)
MFA_ENCRYPTION_KEY=$(fernet)
OIDC_KEY_ENCRYPTION_KEY=$(fernet)
SWA_ENCRYPTION_KEY=$(fernet)
RECIPE_ENCRYPTION_KEY=$(fernet)
EOF
  echo "demo: wrote $ENV_FILE (mode 600). Add CLOUDFLARE_TUNNEL_TOKEN, then: scripts/demo.sh deploy"
}

cmd_deploy() {
  [ -f "$ENV_FILE" ] || die "missing $ENV_FILE (run: scripts/demo.sh init)"
  grep -Eq '^CLOUDFLARE_TUNNEL_TOKEN=.+' "$ENV_FILE" || die "CLOUDFLARE_TUNNEL_TOKEN is empty in $ENV_FILE"
  git -C "$REPO" fetch origin main
  local sha; sha="$(git -C "$REPO" rev-parse origin/main)"
  if [ -d "$SRC" ]; then git -C "$REPO" worktree remove --force "$SRC"; fi
  git -C "$REPO" worktree add --detach "$SRC" "$sha"
  echo "demo: deploying origin/main @ ${sha:0:9}"
  compose up -d --build --remove-orphans
  echo "$sha" > "$DEMO_HOME/deployed-sha"
  cmd_smoke
}

cmd_bootstrap_admin() {
  local email="${1:-}"; [ -n "$email" ] || die "usage: demo.sh bootstrap-admin <admin-email>"
  local password; password="$(token | cut -c1-24)A1!"
  # -i is required: without it docker exec drops the heredoc, python runs nothing and exits 0.
  local out
  out="$(docker exec -i -e A_EMAIL="$email" -e A_PASSWORD="$password" ifora-demo-api python - <<'PY'
import json, os, urllib.request, urllib.error
body = json.dumps({"email": os.environ["A_EMAIL"], "password": os.environ["A_PASSWORD"], "first_name": "Demo",
                   "last_name": "Admin", "secret_key": os.environ["ADMIN_SECRET_KEY"]}).encode()
req = urllib.request.Request("http://localhost:8000/api/v1/admin/bootstrap", body, {"Content-Type": "application/json"})
try:
    print("status", urllib.request.urlopen(req).status)
except urllib.error.HTTPError as e:
    raise SystemExit(f"bootstrap failed: {e.code} {e.read().decode()[:200]}")
PY
)" || die "bootstrap failed: $out"
  case "$out" in "status 200"*|"status 201"*) ;; *) die "bootstrap did not confirm success (got: '$out')";; esac
  echo "demo: admin $email created. Password (shown once, store it in your password manager): $password"
  echo "demo: admin MFA is required; sign in and enrol a TOTP factor before inviting anyone."
}

cmd_smoke() {
  local fail=0
  chk() { # name expected-status path
    local got; got="$(docker exec ifora-demo-edge wget -S -q -O /dev/null "http://127.0.0.1$3" 2>&1 | awk '/HTTP\//{print $2; exit}' || true)"
    [ -n "$got" ] || got=000
    if [ "$got" = "$2" ]; then echo "  ok   $1 ($3 -> $got)"; else echo "  FAIL $1 ($3 -> $got, want $2)"; fail=1; fi
  }
  echo "demo: smoke"
  chk "api health via edge" 200 /health
  chk "oidc discovery via edge" 200 /.well-known/openid-configuration
  chk "frontend via edge" 200 /
  chk "metrics blocked at edge" 404 /metrics
  chk "api docs blocked at edge" 404 /docs
  [ "$fail" = 0 ] || die "smoke test failed"
}

cmd_reset() {
  [ "${1:-}" = "--yes" ] || die "reset deletes the demo database and volumes. Re-run with --yes. (dev/prod is untouched)"
  compose down -v --remove-orphans
  cmd_deploy
  echo "demo: database is empty again. Run: scripts/demo.sh bootstrap-admin <email>"
}

case "${1:-}" in
  init) cmd_init ;;
  deploy) cmd_deploy ;;
  bootstrap-admin) shift; cmd_bootstrap_admin "$@" ;;
  smoke) cmd_smoke ;;
  status) compose ps ;;
  logs) shift; compose logs --tail=100 -f "$@" ;;
  down) compose down ;;
  reset) shift; cmd_reset "$@" ;;
  *) sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
