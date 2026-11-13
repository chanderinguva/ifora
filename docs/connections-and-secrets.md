# Connection workspaces and credential protection

## Product behavior

- Templates and recipe steps create connections in a modal without navigating away or discarding the draft.
- The failed-login Slack template accepts either an incoming webhook or a bot connection. Bot connections ask for a channel/user ID and use the existing typed `post_message` action.
- Organization connections are available to automation administrators, optionally restricted to groups and/or assigned folders. Folder connections inherit use access from the selected folders.
- Folder editor groups can edit drafts and use folder connections. Folder manager groups can publish/manage recipes and assign connections. Existing route-level administrator RBAC still applies; folder membership never turns an ordinary end user into an administrator.
- Connection managers can change/rotate credentials, not read them. Organization connections retain creator management; folder connections follow current folder managers (all assigned folders), or explicitly assigned connection-manager groups. Super administrators retain access.
- Existing `allowed_users` restrictions migrate unchanged as `sharing_scope=legacy`. Editing does not silently broaden them. Selecting Organization/Folder explicitly replaces the legacy policy.
- Groups carrying connection/folder privileges receive the existing privileged-group membership protections: non-super-admin directory changes, SCIM and recipe/group-rule privilege grants are blocked.
- New-style connections recheck the recipe owner's active administrator permissions and current group/folder access when a step executes. Existing legacy published-job behavior stays compatible.
- Moving a recipe checks both its draft and published connection references.
- Folders are intentionally flat in this version. Nested-folder inheritance is not implemented.

## Authentication support

Generic HTTP connections support:
1. No authentication.
2. Basic authentication (both fields encrypted).
3. Bearer tokens (including customer-issued JWT bearer tokens).
4. API keys in headers, query parameters, JSON bodies or form bodies.
5. Multiple custom encrypted secret fields in those destinations.
6. OAuth 2.0 client credentials, using Basic or form client authentication.
7. OAuth 2.0 authorization code with PKCE S256, one-use expiring state, and refresh-token rotation.

OAuth authorization requires `RECIPE_OAUTH_CALLBACK_URL`, an exact public HTTPS URL ending in
`/api/v1/admin/recipe-connections/oauth/callback`. Set it independently for Dev and Demo and register each exact value with the OAuth provider.
The callback is tied to the initiating administrator and connection settings; it does not accept a caller-supplied redirect.
Authorization opens a separate tab so the recipe stays intact. After authorizing an inline connection, return to the recipe; an existing action can then run with the saved grant. The Connections page offers Authorize/Reauthorize.
OAuth token requests and refreshes use the same SSRF, redirect, timeout and response-size restrictions as recipe HTTP requests.
Refreshes serialize with a database row lock. Token endpoints may be on a different explicitly configured HTTPS host from the resource API.

mTLS/client certificates, AWS SigV4, Digest, automatic JWT client assertions and provider-specific signing are **not** supported by this PR.
They need dedicated implementations; a custom header is not presented as a substitute for those protocols.
JSON secret bindings inject top-level fields; nested secret paths are not implemented.
Generic credential-bearing resource requests are pinned to HTTPS port 443. Alternate resource ports are not enabled by this PR.

## Secrets and logs

Connection secrets are write-only, encrypted at rest, and resolved only for execution.
Recipes, published versions and exports carry connection IDs, not secret values.
Known credential headers, query parameters and body fields are refused in newly saved HTTP recipe definitions.
An obsolete Authorization header overwritten by a legacy connection is removed during validation rather than retained in the definition.

Use encrypted bindings for arbitrary credential names; software cannot reliably infer that every arbitrary string is a credential.
Generic HTTP connection history suppresses all request header values, query values and bodies, including dry runs.
Known secret values are scrubbed from returned outputs. Provider errors are reduced to safe messages.
Existing immutable versions are not rewritten automatically; audit any old recipes that previously contained pasted credentials.

Uvicorn access logs omit the OAuth callback query string. Apply the same omission to any upstream access logs, APM and tracing.
OAuth tokens, refresh tokens, client secrets and PKCE verifiers are never returned by connection APIs.

## Secret providers: no paid dependency

The default is the existing application-encrypted Fernet store. `RECIPE_ENCRYPTION_KEY_PREVIOUS` permits a controlled local-key rotation.
Every environment needs independent keys. Keep the retired key until old backups and pending authorizations no longer require it.

The optional provider is **OpenBao 2.7.2**, pinned in `docker/docker-compose.openbao.yml`.
It uses Transit AES-256-GCM: ciphertext remains in Postgres, key material stays in OpenBao.
No Vault Enterprise feature, cloud account, license fee or third-party hosted service is required.
API and worker have separate AppRoles, restricted to encrypt/decrypt one key. They cannot rotate/export keys or administer the vault.
HTTPS verification is mandatory. Redirects and plaintext fallback are disabled.
Ciphertext prefixes permit reading existing Fernet records during a staged migration.
A sealed/unavailable vault prevents secret operations; it never causes plaintext storage.

Separate Dev and Demo Compose projects get separate OpenBao storage/audit volumes, certificates and AppRoles.
A same-host container is useful process separation, **not protection against host/Docker-administrator compromise**.
The local overlay is a single-node deployment, not a highly available service.
It disables memory locking for Docker Desktop and disallows container swap by setting equal memory and memory+swap limits.
For a hosted production service, use a separately operated OpenBao cluster and an appropriate unseal/recovery design.

## Optional Mac setup, one environment at a time

Do not enable the overlay until the new image/code is available and local review is complete.
Keep Docker Desktop running and the Mac awake.

### Dev

Prepare a dedicated directory outside Git:

```bash
python3 scripts/openbao-setup.py prepare --environment dev --directory "$HOME/ifora-secrets/dev"
```

Add these non-secret settings to `docker/.env`, initially leaving the enable flag false:

```dotenv
IFORA_OPENBAO_ENABLED=false
IFORA_OPENBAO_DIR=/Users/YOUR_USER/ifora-secrets/dev
IFORA_OPENBAO_PORT=18200
RECIPE_OAUTH_CALLBACK_URL=https://ifora.app/api/v1/admin/recipe-connections/oauth/callback
```

Use an absolute directory path; Compose dotenv files do not expand `$HOME`.
Keep the existing `RECIPE_ENCRYPTION_KEY` during migration.

Start **only** the vault (no deployed application changes):

```bash
docker compose -p ifora --env-file docker/.env \
  -f docker/docker-compose.yml -f docker/docker-compose.openbao.yml up -d openbao
```

Initialize and unseal it:

```bash
python3 scripts/openbao-setup.py init --directory "$HOME/ifora-secrets/dev"
python3 scripts/openbao-setup.py unseal --directory "$HOME/ifora-secrets/dev"
python3 scripts/openbao-setup.py configure --directory "$HOME/ifora-secrets/dev"
python3 scripts/openbao-setup.py status --directory "$HOME/ifora-secrets/dev"
```

Initialization writes `operator-recovery.json` mode 0600; no recovery key or root token is printed.
The unseal command asks for two distinct shares, hidden; configure asks for the initial operator token, hidden.
Retrieve these locally from the recovery file. Never paste them into chat or Git.
Move recovery material and the CA private key to secure offline storage after setup.
The enclosing directory is mode 0700. Individually mounted server/application credential files are readable inside their respective containers;
their host-side directory prevents access by other host users. Do not loosen the directory permissions or mount the directory wholesale.

AppRole secret IDs expire in **30 days**. Run configure again before expiry and recreate API/worker containers so file bind mounts pick up the new files.
Use a scoped operator token for ongoing management. After initial verification, revoke the initial operator token with `revoke-token`.
Certificates expire after 365 days; renew and replace them deliberately.

Once status says initialized and unsealed and the AppRoles exist:
- Set `IFORA_OPENBAO_ENABLED=true` exactly, without quotes.
- Add the overlay to any manual Compose command used to recreate API/worker.
- CI and `demo.sh` honor this flag and retain the overlay on subsequent deployments.
- Verify a connection can be created, tested and used in a recipe before migrating old records.

### Demo

Repeat with `--environment demo --directory "$HOME/ifora-secrets/demo"`.
Use the Demo dotenv file, project `ifora-demo`, a different loopback port (for example 18201),
and `--url https://localhost:18201` on operator commands.
Use its normal base/production/demo Compose files **plus** the OpenBao overlay.
Set the callback to `https://demo.ifora.app/api/v1/admin/recipe-connections/oauth/callback`.
Never copy Dev's certificates, keys, AppRole files or recovery material into Demo.

### Migration and recovery

Back up Postgres, the OpenBao Raft data/snapshot, the audit volume, and recovery material.
Store recovery material separately from application backups. Prove restoration in a disposable environment first.
Do not destroy a key or vault volume while any live data or retained backup still depends on it.

After activating the provider, run a dry check inside the appropriate API container:

```bash
docker compose -p ifora --env-file docker/.env \
  -f docker/docker-compose.yml -f docker/docker-compose.openbao.yml \
  exec -T backend-api python - --tenant default < scripts/reencrypt-connection-secrets.py
```

After backups and verification, repeat with `--apply` after `--tenant default`.
The script verifies decrypt/encrypt/decrypt for each connection and webhook, then commits one row at a time.
It never prints plaintext/ciphertext and never rotates the remote service credential.

After a vault restart, unseal it before connection-dependent operations. Application startup alone does not imply vault readiness.
A lost vault with no usable snapshot/recovery material can make its encrypted records unrecoverable.
Rollback must preserve the old provider and keys; switching the configured provider does not decrypt old ciphertext.
Migration downgrade refuses to discard active organization/folder sharing semantics.

## Review on Mac before merge

Use a separate PR checkout; don't point disposable tests at Dev/Demo databases or use their dotenv files.
Run the existing disposable backend check with four workers:

```bash
CI_TEST_WORKERS=4 docker compose -p ifora-connections-check \
  -f docker/ci/docker-compose.tests.yml up --abort-on-container-exit --exit-code-from tests
docker compose -p ifora-connections-check -f docker/ci/docker-compose.tests.yml down -v
```

This uses the existing `ifora-ci-backend:py312` test image. Rebuild it using the established CI setup if missing.

Frontend:

```bash
cd frontend
npm run type-check
npm run lint
npm run build
```

Against a disposable/local review stack, set the existing `ADMIN_EMAIL`, `ADMIN_PASSWORD` and optional `ADMIN_TOTP_SECRET` locally, then run:

```bash
npx playwright test e2e/recipe-connectors.spec.ts e2e/connection-workspaces.spec.ts e2e/recipes-m6.spec.ts
```

Manual acceptance:
- Start a Slack template with no connections; create a bot connection inline; retain recipe name/inputs and select the new connection automatically.
- Enter a channel ID, create the draft and verify the typed Slack action.
- Edit an unsaved recipe; create a connection and cancel a second creation; neither action loses the draft.
- Create a folder with editor/manager groups; verify an outsider cannot use its connection or change protected group membership.
- Verify manager/use rights differ, revocation blocks subsequent new-style jobs, and legacy restrictions remain unchanged.
- Add a custom JSON/form/header secret under an arbitrary name; verify request injection and that history/export never exposes it.
- Test Slack scope discovery; missing-scope actions show requirements and cannot run with verified insufficient scopes.
- Authorize OAuth with a disposable provider account; test refresh, cancellation and repeated callback rejection.
- In a disposable vault, seal/restart it and verify secret operations fail without fallback, then unseal and recover.


## Third Docker stack for PR 138 (recommended)

Use a separate checkout of the PR branch. The standalone review Compose file never
includes Dev/Demo overrides, tunnels, published image tags, or their environment files.
Postgres/Redis have no published ports. Only localhost ports 3300 (UI) and 8300 (API)
are bound. The script creates fresh private keys outside Git; do not copy deployed keys/data.
MFA enrollment is required for the new review administrator. Outbound email is not configured.
Use disposable external-service accounts/connections: a published recipe can still call an external API.

```bash
cd /Users/chanderinguva/Development/ifora
git fetch origin feat/connection-workspaces-and-secret-providers
git worktree add ../ifora-pr138-review origin/feat/connection-workspaces-and-secret-providers
cd ../ifora-pr138-review
python3 scripts/review-stack.py up
python3 scripts/review-stack.py bootstrap --email YOUR_EMAIL
```

Enter a new review-only password when prompted, then open `http://localhost:3300/login`.
Keep Dev/Demo running. The first build may take several minutes; later builds reuse Docker layers.
The review stack builds the checked-out source, not the deployed GHCR images.
If a selected port is occupied, startup fails rather than stopping another stack.
Run the manual acceptance checklist above with this disposable administrator/data.
Generic OAuth needs a provider-approved HTTPS callback and is not enabled by this localhost setup.
OpenBao is disabled; its separate setup remains optional and must be tested before activation.

```bash
# Inspect / stop without removing review data:
python3 scripts/review-stack.py status
python3 scripts/review-stack.py stop
# Delete ONLY the disposable review containers, network and database volumes:
python3 scripts/review-stack.py destroy --confirm ifora-pr138-review
```

Review-only keys remain in `~/ifora-local/ifora-pr138-review/review.env` (mode 0600).
Do not use this stack for real customer credentials or copy its environment file into Dev/Demo.
