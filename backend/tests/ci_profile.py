"""Opt-in fixture timing for disposable CI benchmarks; normal test runs do not load this plugin."""
from collections import defaultdict
import json
import os
from pathlib import Path
import time

import pytest

_fixtures = defaultdict(lambda: {"count": 0, "seconds": 0.0})
_phases = defaultdict(float)


@pytest.hookimpl(hookwrapper=True)
def pytest_fixture_setup(fixturedef, request):
    started = time.perf_counter()
    try:
        yield
    finally:
        row = _fixtures[fixturedef.argname]
        row["count"] += 1
        row["seconds"] += time.perf_counter() - started


def pytest_runtest_logreport(report):
    _phases[report.when] += report.duration


def pytest_sessionfinish(session, exitstatus):
    directory = Path("/tmp/ifora-ci-profile")
    directory.mkdir(parents=True, exist_ok=True)
    worker = os.environ.get("PYTEST_XDIST_WORKER", "master")
    (directory / f"{worker}.json").write_text(json.dumps({
        "worker": worker, "exit_status": int(exitstatus),
        "phase_seconds": dict(_phases), "fixtures": dict(_fixtures),
    }, indent=2))
