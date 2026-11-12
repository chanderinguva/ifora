# Backend CI worker isolation

Baseline: build #8 ran all 1728 backend tests in about 14 minutes, with warm test
dependency images. CI uses pytest-xdist 3.8.0 with four workers and loadfile
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

`CI_TEST_WORKERS` accepts 1..4. The pipeline sets 4; set 1 to diagnose an isolation
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

## Measure the next optimization

Build #10 completed in 9m41s: backend 8m09s, frontend 15s, warm images 21s,
demo deployment 25s and dev deployment 34s. Backend is the critical path.
The isolated two-worker Mac verification took 4m39s. Its PostgreSQL/Redis data
directories use tmpfs, whereas Drone's service configuration does not. That is
a concrete storage difference, not proof of its contribution to runtime.
More workers are an experiment, not a guaranteed improvement.

From a checkout containing the benchmark scripts, with Docker running and no
Drone build or other benchmark active:

```sh
python3 scripts/ci-benchmark-backend.py
```

The existing `ifora-ci-backend:py312` dependency image is reused. If missing,
build it with the command above. Each configuration runs the complete suite,
so allow roughly 15–30 minutes for 2, 3 and 4 workers. Keep the Mac plugged in
and awake, and avoid other heavy work. A second pass reduces timing noise:

```sh
python3 scripts/ci-benchmark-backend.py --repeats 2
```

The tool uses a unique `ifora-ci-benchmark-<pid>` project and creates fresh
PostgreSQL/Redis containers for every run. By default an override removes tmpfs,
matching Drone's disk-backed service storage (Compose 2.24+ required; the Mac has
2.33). Compare storage separately with the same worker count:

```sh
python3 scripts/ci-benchmark-backend.py --workers 2 --storage disk
python3 scripts/ci-benchmark-backend.py --workers 2 --storage memory
```

Record the storage mode alongside worker timings; do not mix storage modes when
selecting workers. Changing Drone's storage requires its own measured validation.
The tool removes only that project's
containers/network/volumes afterward, including on Ctrl+C. It does not restart
Drone or either deployed stack, publish ports, or mount the Docker socket/home
inside test containers. Benchmark load still competes for the Mac's resources.
Force-killing Python or shutting down Docker can prevent cleanup; recover using
the exact project name printed in Docker's output, never a global prune.

Results under gitignored `.ci/benchmarks/<timestamp>-<pid>/` include:

- `summary.json`: commit, complete suite counts, exit codes, wall times and fastest
  measured configuration (median for repeated runs). No recommendation is made
  if runs fail, reports are missing, or test/skip counts differ.
- Per-run `tests.log`, JUnit XML and per-worker JSON fixture timings.
- `resources.jsonl`: five-second samples for benchmark containers only, including
  CPU, memory and block I/O. These do not measure overall Mac pressure or prove
  the cause of the earlier Drone/local timing gap.

Profiling is opt-in (`CI_TEST_PROFILE=1`). Normal Drone runs use four workers
and their existing pytest options. The profiler measures fixture **setup** and
aggregate setup/call/teardown phases; fixture times are inclusive and may overlap,
so do not add them together as independent wall times. Use `_clean_db` and
`_clean_redis` measurements to decide whether cleanup warrants a separate change.
No transactions, truncation, cryptography, test selection or deployment health
checks are weakened by this change.

Pick a worker count only after comparable successful runs and a subsequent Drone
validation. Share `summary.json` and worker JSON files to review the results.

## Measured worker selection

The Mac completed a disk-backed benchmark at commit
`8fb314a0a02f351ea69a51a3d1711bfeb0e38559`:

| Workers | Full run wall time | Tests passed | Failures/errors/skips |
| --- | --- | --- | --- |
| 2 | 498.57s (8m19s) | 1729 | 0 / 0 / 0 |
| 3 | 357.87s (5m58s) | 1729 | 0 / 0 / 0 |
| 4 | 296.98s (4m57s) | 1729 | 0 / 0 / 0 |

All runs and cleanup exited 0. Four workers reduced backend benchmark wall time
by 201.59s (40.4%) relative to two workers. Use four in Drone while retaining
runner capacity one, all four isolated databases/Redis DBs and existing deploy
gates. This is one pass per configuration; resource samples have not been
reviewed and sustained stability/end-to-end time need confirmation in Drone.
With unchanged warm-cache overhead, roughly 6–7 minutes total is a planning
estimate, not a measured pipeline result. Source-changing/cold builds can differ.
If the Mac experiences resource pressure or the four-worker run is unstable,
return only `CI_TEST_WORKERS` in `.drone.yml` to `"2"` and rerun; do not reduce
coverage or password hashing settings to meet a timing target.
