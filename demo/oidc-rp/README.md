# Demo OIDC app

A separate web app (own origin, `http://localhost:4000`) that signs users in with IdentityForge as a
third-party relying party: authorization code + PKCE, consent, ID token validation, UserInfo, refresh,
revocation and RP-initiated logout.

1. In IdentityForge, **Admin → Applications → Add application**: leave *First-party* off (so users see the
   consent screen), redirect URI `http://localhost:4000/callback`, post-logout URI `http://localhost:4000/signed-out`.
   Copy the client secret (shown once).
2. Put `DEMO_CLIENT_ID` and `DEMO_CLIENT_SECRET` in `docker/.env`.
3. `docker compose -f docker/docker-compose.yml --profile demo up -d --build demo-app`, then open http://localhost:4000.

State is in memory; restarting the app signs everyone out of it. Not a production template.
