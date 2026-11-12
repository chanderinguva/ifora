"""Pure resource allocation for the bounded, disposable CI worker pool."""
import re
from urllib.parse import urlparse


def worker_resources(env):
    database = env.get("TEST_DB_NAME", "ifora_test")
    redis_db = env.get("TEST_REDIS_DB", "15")
    worker = env.get("PYTEST_XDIST_WORKER", "master")
    if worker == "master":
        return database, redis_db
    match = re.fullmatch(r"gw([0-3])", worker)
    if (
        not match
        or database != "ifora_ci_test"
        or redis_db != "15"
        or urlparse(env.get("DATABASE_URL", "")).hostname != "ci-postgres"
        or urlparse(env.get("DATABASE_URL", "")).username != "ifora_ci"
        or urlparse(env.get("REDIS_URL", "")).hostname != "ci-redis"
    ):
        raise RuntimeError("Parallel tests require disposable CI services and workers gw0..gw3")
    # Logical Redis DBs 11..14 are distinct from the serial test DB 15.
    return f"{database}_{worker}", str(11 + int(match[1]))
