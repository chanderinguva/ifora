# Backend CI worker isolation

Baseline: build #8 ran all 1728 backend tests in about 14 minutes, with warm test
dependency images. CI now uses pytest-xdist 3.8.0 with two workers and loadfile
scheduling: tests within a file stay together, while files run in parallel.

No tests are selected out and no production password hashing settings change.
Each worker runs migrations and keeps per-test TRUNCATE/Redis cleanup:

| Worker | PostgreSQL database | Redis DB |
| --- | --- | --- |
| `gw0` | `ifora_ci_test_gw0` | 11 |
| `gw1` | `ifora_ci_test_gw1` | 12 |
| `gw2` (optional) | `ifora_ci_test_gw2` | 13 |
| `gw3` (optional) | `ifora_ci_test_gw3` | 14 |
| Serial | `ifora_ci_test` | 15 |

Parallel fixture allocation refuses non-CI hostnames, usernames, base DB names,
Redis settings and unexpected worker IDs. The entrypoint still validates exact
disposable endpoints before pytest imports application code. Services remain
ephemeral, without host ports or application data volumes. Keep runner capacity 1.

`CI_TEST_WORKERS` accepts 1..4. The pipeline sets 2; set 1 to diagnose an isolation
issue serially. Crashed workers fail the build without automatic replacements.
Do not increase workers without measuring CPU/memory pressure on the Mac, which
also runs both deployed environments. The dependency image rebuilds once for the
new pytest dependency. No speed improvement is claimed until the full suite passes
on the Mac with the same collected test count. Compare warm runs while awake.

## Verify this PR before merging

From a checkout of this branch on the Mac (no deployed env file):

```sh
docker build -f docker/ci/backend.Dockerfile -t ifora-ci-backend:py312 backend
docker compose -p ifora-ci-check -f docker/ci/docker-compose.tests.yml up --abort-on-container-exit --exit-code-from tests
docker compose -p ifora-ci-check -f docker/ci/docker-compose.tests.yml down --volumes
```

This project has no published ports, shared data volumes, Docker socket or home
mount. Its database and Redis storage are disposable tmpfs. The cleanup command
targets only `ifora-ci-check`. Record the test count and elapsed time; do not
merge on helper tests alone if the full parallel suite fails.
