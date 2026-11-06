"""Integration test fixtures: real FastAPI app against a dedicated Postgres database."""

import os
import sys
from urllib.parse import urlparse, urlunparse

import psycopg2
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

TEST_DB = "identityforge_test"
_base = os.environ["DATABASE_URL"]  # run inside the api container (or export DATABASE_URL)
_u = urlparse(_base)
_test_url = urlunparse(_u._replace(path=f"/{TEST_DB}"))
_async_url = _test_url.replace("+psycopg2", "+asyncpg")

# Must be set before backend.app.* is imported (settings/engine read env at import)
os.environ["DATABASE_URL"] = _test_url
os.environ["DATABASE_URL_ASYNC"] = _async_url
os.environ.setdefault("SECRET_KEY", "test_secret_key_value_with_at_least_32_chars")
os.environ.setdefault("ADMIN_SECRET_KEY", "test_admin_bootstrap_key_with_32_chars_min")
os.environ["ENVIRONMENT"] = "test"
# Isolated Redis database for rate-limit state (never the dev db 0)
_redis_base = os.environ.get("REDIS_URL", "redis://localhost:6379/0").rsplit("/", 1)[0]
os.environ["REDIS_URL"] = f"{_redis_base}/15"


def _ensure_database():
    conn = psycopg2.connect(
        host=_u.hostname, port=_u.port, user=_u.username, password=_u.password, dbname="postgres"
    )
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (TEST_DB,))
        if not cur.fetchone():
            cur.execute(f'CREATE DATABASE "{TEST_DB}"')
    conn.close()


_ensure_database()

from fastapi.testclient import TestClient  # noqa: E402

from backend.app.api import app  # noqa: E402
from backend.app.db import Base, SessionLocal, engine  # noqa: E402

ORIGIN = "http://localhost:3000"
STRONG = "Str0ngPassw0rd!x"


ALEMBIC_INI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "alembic.ini")


def alembic_config():
    from alembic.config import Config

    return Config(ALEMBIC_INI)


def reset_schema():
    """Blank database, then build the schema exactly as production does: via migrations."""
    from alembic import command

    with engine.begin() as conn:
        conn.exec_driver_sql("DROP SCHEMA public CASCADE")
        conn.exec_driver_sql("CREATE SCHEMA public")
    command.upgrade(alembic_config(), "head")


@pytest.fixture(scope="session", autouse=True)
def _schema():
    reset_schema()
    yield


@pytest.fixture(autouse=True)
def _clean_redis():
    import redis

    r = redis.Redis.from_url(os.environ["REDIS_URL"])
    r.flushdb()
    yield
    r.flushdb()


@pytest.fixture(autouse=True)
def _clean_db():
    with engine.begin() as conn:
        names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
        conn.exec_driver_sql(f"TRUNCATE {names} RESTART IDENTITY CASCADE")
    yield


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


def make_user(db, email, password=STRONG, admin=False, super_admin=False, **kw):
    from backend.app.users.model import User

    u = User(
        email=email,
        username=kw.pop("username", email.split("@")[0]),
        first_name=kw.pop("first_name", "Test"),
        last_name=kw.pop("last_name", "User"),
        password=password,
        is_admin=admin or super_admin,
        is_super_admin=super_admin,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


class Api:
    """A browser-like client: keeps the session cookie and CSRF token."""

    def __init__(self):
        self.c = TestClient(app, base_url="http://localhost:8000")
        self.csrf = None

    def login(self, email, password=STRONG):
        r = self.c.post("/api/v1/login", json={"email": email, "password": password}, headers={"Origin": ORIGIN})
        if r.status_code == 200:
            self.csrf = r.json()["csrf_token"]
        return r

    def _h(self, csrf=True):
        h = {"Origin": ORIGIN}
        if csrf and self.csrf:
            h["X-CSRF-Token"] = self.csrf
        return h

    def get(self, url, **kw):
        return self.c.get("/api/v1" + url, **kw)

    def post(self, url, json=None, csrf=True):
        return self.c.post("/api/v1" + url, json=json, headers=self._h(csrf))

    def patch(self, url, json=None, csrf=True):
        return self.c.patch("/api/v1" + url, json=json, headers=self._h(csrf))

    def delete(self, url, csrf=True):
        return self.c.delete("/api/v1" + url, headers=self._h(csrf))


@pytest.fixture
def anon():
    return Api()


@pytest.fixture
def super_admin(db):
    u = make_user(db, "root@example.com", super_admin=True)
    a = Api()
    assert a.login(u.email).status_code == 200
    a.user = u
    return a


@pytest.fixture
def admin(db):
    u = make_user(db, "admin@example.com", admin=True)
    a = Api()
    assert a.login(u.email).status_code == 200
    a.user = u
    return a


@pytest.fixture
def member(db):
    u = make_user(db, "member@example.com")
    a = Api()
    assert a.login(u.email).status_code == 200
    a.user = u
    return a
