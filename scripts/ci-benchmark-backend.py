"""Compare full backend suites on the Mac without changing Drone or deployed stacks.

Requires Python 3 and Docker Compose. Uses a unique disposable Compose project,
an existing dependency image, and fresh database/Redis containers for each run.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "ifora-ci-backend:py312"


def report_summary(directory):
    root = ET.parse(directory / "junit.xml").getroot()
    suites = list(root.iter("testsuite"))
    return {
        key: sum(int(suite.get(key, "0")) for suite in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }


def recommendation(results):
    if not results or any(row["exit_code"] or row.get("cleanup_code") or row.get("report_error") for row in results):
        return None
    reports = [row["report"] for row in results]
    if any(r["failures"] or r["errors"] or not r["tests"] for r in reports):
        return None
    if len({(r["tests"], r["skipped"]) for r in reports}) != 1:
        return None
    groups = {}
    for row in results:
        groups.setdefault(row["workers"], []).append(row["seconds"])
    import statistics
    return min(groups, key=lambda workers: statistics.median(groups[workers]))


def sample_resources(compose, directory, stop):
    with (directory / "resources.jsonl").open("w") as output:
        while not stop.wait(5):
            try:
                ids = subprocess.check_output(compose + ["ps", "-q"], text=True, timeout=10).split()
                if not ids:
                    continue
                stats = subprocess.check_output(
                    ["docker", "stats", "--no-stream", "--format", "{{json .}}", *ids],
                    text=True, timeout=10,
                )
                for line in stats.splitlines():
                    output.write(json.dumps({"time": time.time(), "stats": json.loads(line)}) + "\n")
                output.flush()
            except (OSError, ValueError, subprocess.SubprocessError):
                # Resource sampling is diagnostic and must not interrupt tests.
                continue


def run_once(compose, workers, directory):
    directory.mkdir(parents=True)
    env = {**os.environ, "CI_TEST_WORKERS": str(workers), "CI_TEST_PROFILE": "1"}
    stop = threading.Event()
    sampler = threading.Thread(target=sample_resources, args=(compose, directory, stop), daemon=True)
    started = time.monotonic()
    sampler.start()
    result = {"workers": workers, "exit_code": 1}
    process = None
    try:
        with (directory / "tests.log").open("w") as log:
            process = subprocess.Popen(
                compose + ["up", "--abort-on-container-exit", "--exit-code-from", "tests"],
                cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            for line in process.stdout:
                print(line, end="", flush=True)
                log.write(line)
            result["exit_code"] = process.wait()
        result["seconds"] = round(time.monotonic() - started, 2)
        profiles = directory / "profiles"
        profiles.mkdir()
        copied = subprocess.run(
            compose + ["cp", "tests:/tmp/ifora-ci-profile/.", str(profiles)], cwd=ROOT,
            capture_output=True, text=True,
        )
        try:
            if copied.returncode:
                raise ValueError("Could not copy pytest reports")
            result["report"] = report_summary(profiles)
        except (OSError, ValueError, ET.ParseError) as error:
            result["report_error"] = str(error)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        stop.set()
        sampler.join(timeout=25)
        # Exact project only; never prune images, builders or any other project.
        result["cleanup_code"] = subprocess.run(compose + ["down", "--volumes"], cwd=ROOT).returncode
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", nargs="+", type=int, choices=(2, 3, 4), default=[2, 3, 4])
    parser.add_argument("--repeats", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--storage", choices=("disk", "memory"), default="disk",
                        help="disk matches Drone; memory matches the local verification stack")
    options = parser.parse_args()
    if len(set(options.workers)) != len(options.workers):
        parser.error("Each worker count must appear only once")
    # Do not silently subset tests or inherit a caller's pytest flags.
    if os.environ.get("PYTEST_ADDOPTS"):
        parser.error("Unset PYTEST_ADDOPTS before benchmarking the complete suite")
    subprocess.run(["docker", "compose", "version"], check=True)
    inspected = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True)
    if inspected.returncode:
        parser.error("Build the dependency image first: docker build -f docker/ci/backend.Dockerfile -t ifora-ci-backend:py312 backend")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = ROOT / ".ci" / "benchmarks" / f"{stamp}-{os.getpid()}"
    output.mkdir(parents=True)
    project = f"ifora-ci-benchmark-{os.getpid()}"
    compose = ["docker", "compose", "-p", project, "-f", str(ROOT / "docker/ci/docker-compose.tests.yml")]
    if options.storage == "disk":
        compose += ["-f", str(ROOT / "docker/ci/docker-compose.benchmark.yml")]
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    results = []
    try:
        for repeat in range(1, options.repeats + 1):
            # Reverse every other pass to reduce fixed-order thermal/cache bias.
            order = options.workers if repeat % 2 else list(reversed(options.workers))
            for workers in order:
                print(f"\nBenchmark: {workers} workers, repeat {repeat}; results: {output}", flush=True)
                row = run_once(compose, workers, output / f"{repeat}-{workers}-workers")
                results.append(row)
                (output / "summary.json").write_text(json.dumps({
                    "commit": revision.stdout.strip(), "storage": options.storage, "results": results,
                    "fastest_measured_workers": recommendation(results),
                }, indent=2))
                if row["exit_code"] or row.get("cleanup_code") or row.get("report_error"):
                    print("Benchmark stopped after a failed run; inspect tests.log.", file=sys.stderr)
                    return 1
    except KeyboardInterrupt:
        print("Benchmark interrupted; disposable project cleanup requested.", file=sys.stderr)
        return 130
    fastest = recommendation(results)
    print(f"\nResults: {output / 'summary.json'}")
    print(f"Fastest measured worker count: {fastest}" if fastest else "Results are not comparable; no worker recommendation.")
    return 0 if fastest else 1


if __name__ == "__main__":
    sys.exit(main())
