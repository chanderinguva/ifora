# Private dev access on ifora.app

This is an opt-in addition to Compose project `ifora`. It keeps the existing
database, Redis, credentials, issuer hostname and application login. Demo and
Drone are not reconfigured. It adds `ifora-dev-edge` and `ifora-dev-tunnel`.

## Cloudflare setup (before enabling)

1. Access → Applications → Self-hosted: create **Ifora Dev** with exact hostnames
   **ifora.app** and **api.ifora.app**, no path restrictions. Do not use a wildcard
   that would include demo or Drone. Allow only your exact email with your chosen
   identity provider or email PIN; no Everyone/Bypass policy. If both hosts are in
   one application, they share the same AUD. Keep Ifora's own login and MFA enabled.
2. Networks → Tunnels: create **ifora-dev** and save its token as
   `IFORA_DEV_TUNNEL_TOKEN` in the existing, gitignored `docker/.env` on the Mac.
   Keep mode 600. Do not store it in Git or paste it into logs/chat.
3. Add these published application routes to **that tunnel only**:

   | Hostname | Service URL | Path |
   | --- | --- | --- |
   | `ifora.app` | `http://dev-edge:80` | blank |
   | `api.ifora.app` | `http://dev-edge:80` | blank |

4. On BOTH routes, enable **Additional application settings → Access → Protect
   with Access** (wording may vary). Set your Access team name and the **Ifora Dev**
   application's AUD. This makes cloudflared validate the Access JWT before
   forwarding. Do not enable routing without the Access policy and validation.
5. If an existing A/AAAA/CNAME record conflicts, record its old value and replace
   only that exact hostname with the tunnel route; leave demo and Drone alone.
   Review existing router forwards and any separate local Caddy listener: an
   alternate publicly reachable route could bypass Access. This override does not
   remove an `edge` service defined in your private, untracked local override.

References:
- https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/
- https://developers.cloudflare.com/tunnel/reference/origin-parameters/#access-settings

## Enable after merging

Update the Mac checkout, then add the exact, unquoted line to `docker/.env`:

```dotenv
IFORA_DEV_ACCESS_ENABLED=true
```

Keep existing strong secrets, HTTPS `OIDC_ISSUER=https://api.ifora.app`, and
`WEBAUTHN_RP_ID=ifora.app` / `WEBAUTHN_ORIGINS=["https://ifora.app"]` settings.
The override forces secure cookies, public UI/login URLs on ifora.app, and
same-origin browser API requests. It keeps Access SSO disabled: Access is an
outer gate, not authority to auto-create or elevate Ifora accounts.

CI checks the flag in the Mac's env file during image build AND deployment. Set
it before triggering the next main build; it builds the correct frontend API
URL, starts both new services, and checks the internal edge. With the flag absent
the existing deployment path is preserved. Avoid toggling it mid-build.

Do not run a plain base-only Compose command after enabling: it can restore old
frontend/environment settings. Keep the dev-access override after your local
override and before `docker-compose.ci.yml` in any manual image-based deployment.
CI keeps bind-mounted config under `~/ifora-local/src-ci`, outside its temporary
checkout, so restarts can still read the Caddyfile. The edge has its own network
172.31.78.0/24 (verify no collision before enabling); only 172.31.78.2 is trusted
for forwarded client IPs. The new ingress has no host ports. Frontend/API host
ports are loopback-only; PostgreSQL and Redis remain on their existing settings.

## Verify before considering it complete

- From a private browser on cellular, both hostnames must show Access login.
- An email not allowed by policy must be denied; neither hostname may bypass it.
- After Access login, sign into Ifora normally; exercise user/admin API calls,
  logout and passkeys if configured. Browser calls must stay on ifora.app.
- Confirm direct API access also requires Access. External OIDC/SAML/SCIM clients,
  recipe webhooks and automation may need a separate reviewed service-token
  design; do not add public bypasses to make integrations work.
- Confirm demo and Drone still behave as before. Existing local `/etc/hosts`
  mappings can bypass public DNS; test from another device to validate the gate.

Internal deployment health checks do not prove Cloudflare policy enforcement.
If enabling fails, stop only `ifora-dev-tunnel`, remove the enable flag, then
redeploy with the prior known-good images/configuration. Keep both hostnames'
Access policies in place. Removing the flag alone does not stop an already
running connector or migrate a frontend back to its previous API URL.
