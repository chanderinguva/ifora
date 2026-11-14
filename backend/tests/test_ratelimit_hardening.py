"""IFORA-22: credential throttling fails closed, counts atomically, and cannot be used to lock out the owner."""

import statistics
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
import redis
from fastapi import HTTPException

from backend.app import mailer, ratelimit
from backend.app.config import settings
from tests.conftest import Api, STRONG, make_user

PEER = "testclient"  # what TestClient reports as the client address


class _DeadRedis:
    """Stands in for an unreachable Redis: every call raises like a refused connection."""

    def __getattr__(self, name):
        def boom(*a, **k):
            raise redis.ConnectionError("down")

        return boom

    def pipeline(self, *a, **k):
        return self


@pytest.fixture
def redis_down(monkeypatch):
    monkeypatch.setattr(ratelimit, "_redis", lambda: _DeadRedis())


@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setitem(mailer.overrides, "send", sent.append)
    return sent


# --- 1. fail closed -------------------------------------------------------------------------------------------------


def test_login_is_refused_when_redis_is_down_and_no_password_is_checked(db, redis_down, monkeypatch):
    u = make_user(db, "down@example.com")
    called = []
    monkeypatch.setattr(type(u), "verify_password", lambda self, pw: called.append(1) or True)
    r = Api().login(u.email, STRONG)
    assert r.status_code == 503 and "csrf_token" not in r.json()
    assert called == []  # the password was never even compared
    assert r.headers.get("retry-after")


def test_mfa_login_reset_and_bootstrap_are_refused_when_redis_is_down(db, redis_down, outbox):
    u = make_user(db, "down2@example.com")
    a = Api()
    assert a.post("/login/mfa", {"mfa_token": "x", "code": "000000"}, csrf=False).status_code == 503
    assert a.post("/auth/forgot-password", {"email": u.email}, csrf=False).status_code == 503
    assert a.post("/auth/reset-password", {"token": "x" * 30, "new_password": STRONG}, csrf=False).status_code == 503
    assert outbox == []


def test_non_credential_scopes_still_fail_open(redis_down):
    ratelimit.check("avatar", "u1", 5)  # an upload limit is not a guessing defence
    ratelimit.consume("email_test", "u1", 5, 60)


def test_rollback_flag_restores_fail_open(db, redis_down, monkeypatch):
    u = make_user(db, "flag@example.com")
    monkeypatch.setattr(settings, "RATE_LIMIT_FAIL_CLOSED", False)
    assert Api().login(u.email, STRONG).status_code == 200


def test_signed_in_sessions_keep_working_while_redis_is_down(db, monkeypatch):
    u = make_user(db, "keep@example.com")
    a = Api()
    assert a.login(u.email, STRONG).status_code == 200
    monkeypatch.setattr(ratelimit, "_redis", lambda: _DeadRedis())
    assert a.get("/me").status_code == 200


def test_redis_errors_are_counted_for_metrics(redis_down):
    before = ratelimit.stats()["redis_errors"]
    with pytest.raises(HTTPException):
        ratelimit.check("login", "1.2.3.4", 5)
    assert ratelimit.stats()["redis_errors"] == before + 1


# --- 2. atomic counting ---------------------------------------------------------------------------------------------


def test_concurrent_requests_at_the_limit_admit_exactly_the_limit():
    limit, callers = 5, 24
    admitted, refused = [], []
    gate = threading.Barrier(callers)

    def go():
        gate.wait()
        try:
            ratelimit.consume("pwreset_ip", "9.9.9.9", limit, 60)
            admitted.append(1)
        except HTTPException as e:
            assert e.status_code == 429
            refused.append(1)

    threads = [threading.Thread(target=go) for _ in range(callers)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(admitted) == limit and len(refused) == callers - limit


def test_two_concurrent_hits_at_limit_minus_one_admit_only_one():
    ratelimit.consume("pwreset_ip", "8.8.8.8", 3, 60)
    ratelimit.consume("pwreset_ip", "8.8.8.8", 3, 60)  # now at limit-1
    results = []
    gate = threading.Barrier(2)

    def go():
        gate.wait()
        try:
            ratelimit.consume("pwreset_ip", "8.8.8.8", 3, 60)
            results.append("ok")
        except HTTPException:
            results.append("429")

    ts = [threading.Thread(target=go) for _ in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(results) == ["429", "ok"]


def test_the_window_starts_at_the_first_hit_and_does_not_slide():
    ratelimit.hit("login", "7.7.7.7", 30)
    first = ratelimit._redis().ttl(ratelimit._key("login", "7.7.7.7"))
    time.sleep(1.1)
    ratelimit.hit("login", "7.7.7.7", 30)
    assert ratelimit._redis().ttl(ratelimit._key("login", "7.7.7.7")) < first


# --- 3. guessing against a locked account from a known address ------------------------------------------------------


def _lock(db, u):
    u.lockout_until = datetime.now(timezone.utc) + timedelta(hours=1)
    db.commit()
    ratelimit._redis().sadd(f"kip:{u.id}", PEER)


def test_known_address_can_still_get_in_while_locked(db):
    u = make_user(db, "owner@example.com")
    _lock(db, u)
    assert Api().login(u.email, STRONG).status_code == 200


def test_wrong_passwords_while_locked_are_counted_then_refused_everywhere(db, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_LOGIN_FAILURES", 1000)  # isolate the per-account cap from the per-IP one
    monkeypatch.setattr(settings, "RATE_LIMIT_LOCKED_GUESSES", 5)
    u = make_user(db, "guessed@example.com")
    _lock(db, u)
    until = u.lockout_until
    a = Api()
    for _ in range(5):
        assert a.login(u.email, "Wrong-guess-1!").status_code == 401
    # cap reached: even the right password is refused from the known address, with the same body as any refusal
    r = a.login(u.email, STRONG)
    assert r.status_code == 401 and r.json() == Api().login("nobody@example.com", "x").json()
    db.refresh(u)
    assert u.lockout_until == until  # the lockout window never grew


def test_twenty_wrong_passwords_while_locked_hit_429_and_do_not_extend_the_lockout(db):
    u = make_user(db, "twenty@example.com")
    _lock(db, u)
    until = u.lockout_until
    codes = [Api().login(u.email, "Wrong-guess-1!").status_code for _ in range(20)]
    assert codes[:10] == [401] * 10 and set(codes[10:]) == {429}
    db.refresh(u)
    assert u.lockout_until == until


def test_spoofed_forwarded_for_header_does_not_dodge_the_limit(db):
    u = make_user(db, "spoof@example.com")
    codes = []
    for i in range(14):
        r = Api().c.post(
            "/api/v1/login",
            json={"email": u.email, "password": "Wrong-guess-1!"},
            headers={"Origin": "http://localhost:3000", "X-Forwarded-For": f"203.0.113.{i}"},
        )
        codes.append(r.status_code)
    assert 429 in codes


# --- 4/5. password reset --------------------------------------------------------------------------------------------


def test_reset_for_known_and_unknown_addresses_look_the_same_and_take_the_same_time(db, outbox):
    make_user(db, "real2@example.com")
    known, unknown = [], []
    for i in range(12):
        a, b = Api(), Api()
        t = time.perf_counter()
        r1 = a.post("/auth/forgot-password", {"email": "real2@example.com"}, csrf=False)
        known.append(time.perf_counter() - t)
        t = time.perf_counter()
        r2 = b.post("/auth/forgot-password", {"email": f"ghost{i}@example.com"}, csrf=False)
        unknown.append(time.perf_counter() - t)
        if r1.status_code == 429:
            break  # the per-address cap is reached on purpose: stop comparing and use what we have
        assert r1.status_code == r2.status_code == 200 and r1.json() == r2.json()
        ratelimit.reset("pwreset_ip", PEER)
        for k in ratelimit._redis().keys("rl:pwreset_email_ip:*"):
            ratelimit._redis().delete(k)
    assert abs(statistics.median(known) - statistics.median(unknown)) < 0.05


def test_an_attacker_cannot_use_up_the_owners_reset_quota(db, outbox, monkeypatch):
    owner = make_user(db, "victim@example.com")
    attacker = Api()
    codes = [attacker.post("/auth/forgot-password", {"email": owner.email}, csrf=False).status_code for _ in range(5)]
    assert codes[:3] == [200] * 3 and codes[3:] == [429, 429]  # the attacker is capped for that email
    outbox.clear()
    monkeypatch.setattr(ratelimit, "client_ip", lambda request: "198.51.100.7")  # the owner, from elsewhere
    r = Api().post("/auth/forgot-password", {"email": owner.email}, csrf=False)
    assert r.status_code == 200 and len(outbox) == 1 and outbox[0]["To"] == owner.email


def test_reset_buckets_are_scoped_to_the_tenant(outbox):
    Api().post("/auth/forgot-password", {"email": "Scoped@example.com"}, csrf=False)
    keys = sorted(k.decode() for k in ratelimit._redis().keys("rl:pwreset_email*"))
    assert len(keys) == 2
    assert keys[0].startswith("rl:pwreset_email:") and keys[0].endswith(":scoped@example.com")
    assert keys[0].split(":")[2].isdigit()  # tenant id sits in front of the address
