"""Rate limiting and idle session timeout."""

from datetime import datetime, timedelta, timezone

from backend.app.auth.session import Session as AuthSession
from backend.app.config import settings
from tests.conftest import STRONG, Api, make_user


def test_login_is_throttled_per_ip_across_unknown_accounts():
    api = Api()
    for i in range(settings.RATE_LIMIT_LOGIN_FAILURES):
        assert api.login(f"ghost{i}@example.com", "WrongPassw0rd!!").status_code == 401
    r = api.login("ghost-final@example.com", "WrongPassw0rd!!")
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) > 0


def test_throttle_blocks_even_the_correct_password(db):
    make_user(db, "a@example.com")
    api = Api()
    for i in range(settings.RATE_LIMIT_LOGIN_FAILURES):
        api.login(f"ghost{i}@example.com", "WrongPassw0rd!!")
    assert api.login("a@example.com", STRONG).status_code == 429


def test_successful_login_does_not_reset_the_failure_count(db):
    make_user(db, "a@example.com")
    api = Api()
    for i in range(settings.RATE_LIMIT_LOGIN_FAILURES - 1):
        api.login(f"ghost{i}@example.com", "WrongPassw0rd!!")
    assert api.login("a@example.com", STRONG).status_code == 200  # success, still counted window
    api.login("ghost-x@example.com", "WrongPassw0rd!!")  # 10th failure
    assert api.login("ghost-y@example.com", "WrongPassw0rd!!").status_code == 429


def test_successful_logins_alone_are_not_throttled(db):
    make_user(db, "a@example.com")
    for _ in range(settings.RATE_LIMIT_LOGIN_FAILURES + 3):
        assert Api().login("a@example.com", STRONG).status_code == 200


def test_bootstrap_key_guessing_is_throttled():
    api = Api()
    body = {"email": "b@example.com", "password": STRONG, "first_name": "B", "last_name": "B", "secret_key": "wrong"}
    for _ in range(settings.RATE_LIMIT_BOOTSTRAP_ATTEMPTS):
        assert api.c.post("/api/v1/admin/bootstrap", json=body).status_code == 403
    assert api.c.post("/api/v1/admin/bootstrap", json=body).status_code == 429


def test_idle_session_expires(member, db):
    assert member.get("/me").status_code == 200
    s = db.query(AuthSession).one()
    s.last_activity_at = datetime.now(timezone.utc) - timedelta(minutes=settings.SESSION_IDLE_TIMEOUT_MINUTES + 1)
    db.commit()
    assert member.get("/me").status_code == 401
    db.refresh(s)
    assert s.status == "expired"


def test_activity_keeps_session_alive(member, db):
    s = db.query(AuthSession).one()
    s.last_activity_at = datetime.now(timezone.utc) - timedelta(minutes=settings.SESSION_IDLE_TIMEOUT_MINUTES - 5)
    db.commit()
    assert member.get("/me").status_code == 200
    db.refresh(s)
    assert datetime.now(timezone.utc) - s.last_activity_at < timedelta(minutes=1)
