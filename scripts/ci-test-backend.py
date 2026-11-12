"""Run backend tests only against Drone's disposable database services.

Fixtures reset schemas and flush Redis. Refuse other endpoints before importing
application/test code so a misconfigured pipeline fails without touching a stack.
"""
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlparse


def validate_endpoints():
    database = urlparse(os.environ["DATABASE_URL"])
    redis = urlparse(os.environ["REDIS_URL"])
    if (
        database.scheme != "postgresql+psycopg2"
        or database.hostname != "ci-postgres"
        or database.port != 5432
        or database.username != "ifora_ci"
        or database.path != "/postgres"
        or database.query
        or redis.scheme != "redis"
        or redis.hostname != "ci-redis"
        or redis.port != 6379
        or redis.path != "/0"
        or redis.query
        or os.environ.get("TEST_DB_NAME") != "ifora_ci_test"
        or os.environ.get("TEST_REDIS_DB") != "15"
    ):
        raise SystemExit("Refusing tests: endpoints must be disposable CI services.")
    return database


def wait_for_services(database, timeout=90):
    import psycopg2
    import redis

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            conn = psycopg2.connect(
                host=database.hostname, port=database.port,
                user=database.username, password=database.password,
                dbname="postgres", connect_timeout=3,
            )
            conn.close()
            client = redis.Redis.from_url(
                os.environ["REDIS_URL"], socket_connect_timeout=3, socket_timeout=3
            )
            try:
                client.ping()
            finally:
                client.close()
            return
        except (psycopg2.OperationalError, redis.exceptions.RedisError):
            time.sleep(2)
    raise SystemExit("Disposable CI PostgreSQL/Redis did not become ready within 90 seconds.")


def main():
    database = validate_endpoints()
    wait_for_services(database)
    backend = Path(__file__).resolve().parents[1] / "backend"
    workers = os.environ.get("CI_TEST_WORKERS", "2")
    if workers not in {"1", "2", "3", "4"}:
        raise SystemExit("CI_TEST_WORKERS must be 1..4 (default 2)")
    args = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--durations=25"]
    if os.environ.get("CI_TEST_PROFILE") == "1":
        args += ["-p", "tests.ci_profile", "--junitxml=/tmp/ifora-ci-profile/junit.xml"]
    if workers != "1":
        args += ["-n", workers, "--dist=loadfile", "--max-worker-restart=0"]
    print(f"Running complete backend suite with {workers} isolated worker(s)", flush=True)
    return subprocess.call(
        args,
        cwd=backend,
    )


if __name__ == "__main__":
    sys.exit(main())

