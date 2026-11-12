# Drone maintenance on this Mac

Image versions verified against Docker Hub on 2026-11-12 (all include linux/arm64):

| Service | Pinned image |
| --- | --- |
| Server | `drone/drone:2.28.2` |
| Docker runner | `drone/drone-runner-docker:1.8.5` |
| Tunnel | `cloudflare/cloudflared:2026.10.7` |

The server and runner replace the floating `:2` and `:1` aliases with their
current release versions. A Compose edit does not update existing containers.
After merging and updating the local checkout, apply the tunnel independently:

```sh
docker compose -p ifora-drone -f docker/drone/docker-compose.drone.yml \
  --env-file docker/drone/.env.drone --profile tunnel pull tunnel
docker compose -p ifora-drone -f docker/drone/docker-compose.drone.yml \
  --env-file docker/drone/.env.drone --profile tunnel up -d --no-deps tunnel
docker logs --since 2m ifora-drone-tunnel
```

Confirm the new version and registered HTTP/2 connections. The connector is
kept on IPv4 explicitly because newer releases default to automatic address
family selection. Upgrading is not proof that the intermittent outage is fixed.

Update the server and runner only when no build is running. Take a backup of
the Drone SQLite data volume before updating the server. Then use the same
Compose invocation with `pull drone runner` and `up -d drone runner` (omit the
profile flag if desired). This briefly interrupts the Drone UI. Do not make
the pipeline restart its own server or runner.

For an attended build, keep the Mac plugged in with its lid open and run
`caffeinate -is` in a separate terminal; Ctrl+C releases the sleep assertion.
This prevents idle sleep but cannot prevent network loss or every system pause.

Build #7 passed all 1728 backend tests in pytest's reported 809.17 seconds,
while Drone displayed 1h14m13s for that step. That discrepancy remains under
investigation. Dependency caching does not eliminate the actual test runtime.
