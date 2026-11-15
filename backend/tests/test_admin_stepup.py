"""IFORA-33: sensitive administrator actions need a recent second-factor proof (step-up)."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from backend.app import ratelimit
from backend.app.audit.model import AuditAction, AuditEvent
from backend.app.auth.session import Session as AuthSession
from backend.app.config import settings
from backend.app.policies.models import NetworkZone
from tests.conftest import Api, make_user
from tests.test_admin_mfa_policy import give_code
from tests.test_mfa import enrol, mfa_login, reset_replay, totp_for
from tests.test_ratelimit_hardening import _DeadRedis

ZONE = {"name": "Office", "cidrs": ["10.0.0.0/8"]}


@pytest.fixture(autouse=True)
def policy_on(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_MFA_REQUIRED", True)


@pytest.fixture
def boss(db):
    """A super administrator who has enrolled an authenticator, signed in with the password only (no proof yet)."""
    u = make_user(db, "boss@example.com", super_admin=True)
    a = Api()
    assert a.login(u.email).status_code == 200
    a.codes = enrol(a, db, u.email, give_code(db, u))
    a.user = u
    return a


def zones(db):
    db.expire_all()
    return db.query(NetworkZone).count()


def events(db, action):
    db.expire_all()
    return db.scalars(select(AuditEvent).where(AuditEvent.action == action)).all()


def test_a_sensitive_action_without_proof_is_refused_and_changes_nothing(db, boss):
    r = boss.post("/admin/network-zones", ZONE)
    assert r.status_code == 403 and r.json()["detail"] == "stepup_required"
    assert r.headers["x-step-up"] == "required"
    assert zones(db) == 0 and events(db, AuditAction.NETWORK_ZONE_CREATED) == []


def test_after_step_up_the_change_succeeds_and_the_audit_event_names_the_method(db, boss):
    assert boss.post("/me/step-up", {"code": totp_for(db, boss.user.email)}).status_code == 200
    r = boss.post("/admin/network-zones", ZONE)
    assert r.status_code == 201, r.text
    (ev,) = events(db, AuditAction.NETWORK_ZONE_CREATED)
    assert ev.event_metadata["stepup"] == "totp"
    (up,) = events(db, AuditAction.ADMIN_STEPUP)
    assert up.event_metadata["method"] == "totp"


def test_a_recovery_code_also_steps_up_and_is_spent(db, boss):
    code = boss.codes[0]
    r = boss.post("/me/step-up", {"code": code})
    assert r.status_code == 200 and r.json()["method"] == "recovery"
    assert boss.post("/admin/network-zones", ZONE).status_code == 201
    assert boss.post("/me/step-up", {"code": code}).status_code == 403  # spent: one use only


def test_the_proof_expires(db, boss):
    boss.post("/me/step-up", {"code": totp_for(db, boss.user.email)})
    assert boss.post("/admin/network-zones", ZONE).status_code == 201
    db.expire_all()
    db.query(AuthSession).filter(AuthSession.user_id == boss.user.id).update({"stepup_at": datetime.now(timezone.utc) - timedelta(minutes=settings.ADMIN_STEPUP_MINUTES + 1)})
    db.commit()
    r = boss.put("/admin/network-zones/1", ZONE)
    assert r.status_code == 403 and r.json()["detail"] == "stepup_required"


def test_a_fresh_mfa_sign_in_counts_as_proof(db, boss):
    s, _, r2 = mfa_login(db, boss.user.email)
    assert r2.status_code == 200
    assert s.post("/admin/network-zones", ZONE).status_code == 201
    (ev,) = events(db, AuditAction.NETWORK_ZONE_CREATED)
    assert ev.event_metadata["stepup"] == "login_mfa"
    db.expire_all()
    sess = db.query(AuthSession).filter(AuthSession.user_id == boss.user.id).order_by(AuthSession.id.desc()).first()
    sess.auth_time = datetime.now(timezone.utc) - timedelta(minutes=settings.ADMIN_STEPUP_MINUTES + 1)  # the sign-in itself ages out too
    db.commit()
    assert s.post("/admin/network-zones", {"name": "Second", "cidrs": ["172.16.0.0/12"]}).status_code == 403


def test_wrong_codes_are_throttled_and_logged(db, boss, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_MFA_FAILURES", 3)
    for _ in range(3):
        assert boss.post("/me/step-up", {"code": "000000"}).status_code == 403
    reset_replay(db, boss.user.email)
    r = boss.post("/me/step-up", {"code": totp_for(db, boss.user.email)})
    assert r.status_code == 429  # even the right code is refused while throttled
    assert boss.post("/admin/network-zones", ZONE).status_code == 403
    assert len(events(db, AuditAction.ADMIN_STEPUP_FAILED)) == 3
    assert len(events(db, AuditAction.ADMIN_STEPUP_THROTTLED)) >= 1


def test_a_replayed_authenticator_code_is_refused(db, boss):
    code = totp_for(db, boss.user.email)
    assert boss.post("/me/step-up", {"code": code}).status_code == 200
    assert boss.post("/me/step-up", {"code": code}).status_code == 403  # the same 30-second code cannot be used twice


def test_rate_limit_store_down_fails_closed(db, boss, monkeypatch):
    monkeypatch.setattr(ratelimit, "_redis", lambda: _DeadRedis())
    assert boss.post("/me/step-up", {"code": totp_for(db, boss.user.email)}).status_code == 503
    assert boss.post("/admin/network-zones", ZONE).status_code == 403  # nothing was granted


def test_only_administrators_can_step_up(db, member):
    assert member.post("/me/step-up", {"code": "123456"}).status_code == 403


def test_an_administrator_without_an_authenticator_gets_a_clear_refusal_not_a_pass(db, admin):
    r = admin.post("/me/step-up", {"code": "123456"})  # e.g. a passkey-only admin: they re-confirm by signing in again
    assert r.status_code == 400 and "passkey" in r.json()["detail"]
    assert admin.get("/me/step-up").json()["fresh"] is False


@pytest.mark.parametrize("method,path,body", [
    ("PUT", "/admin/roles/users/1", {"roles": []}),
    ("PUT", "/admin/roles/groups/1", {"roles": []}),
    ("POST", "/admin/scim/tokens", {}),
    ("POST", "/admin/provisioning-apps", {}),
    ("DELETE", "/admin/network-zones/1", None),
    ("PUT", "/admin/applications/1/policy", {}),
    ("DELETE", "/admin/applications/1/policy", None),
])
def test_every_sensitive_route_demands_step_up(boss, method, path, body):
    r = getattr(boss, method.lower())(path, body) if body is not None else getattr(boss, method.lower())(path)
    assert r.status_code == 403 and r.json()["detail"] == "stepup_required", (method, path, r.status_code, r.text[:120])


def test_non_sensitive_admin_routes_are_unchanged(db, boss):
    assert boss.get("/admin/users").status_code == 200
    assert boss.get("/admin/network-zones").status_code == 200


def test_step_up_is_off_where_admin_mfa_is_not_required(db, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_MFA_REQUIRED", False)
    u = make_user(db, "plain@example.com", super_admin=True)
    a = Api()
    a.login(u.email)
    assert a.post("/admin/network-zones", ZONE).status_code == 201  # behaviour unchanged for deployments without the policy


def test_the_status_endpoint_reports_freshness(db, boss):
    s = boss.get("/me/step-up").json()
    assert s["required"] is True and s["fresh"] is False and s["expires_at"] is None
    boss.post("/me/step-up", {"code": totp_for(db, boss.user.email)})
    s = boss.get("/me/step-up").json()
    assert s["fresh"] is True and s["window_minutes"] == settings.ADMIN_STEPUP_MINUTES and s["expires_at"]


def test_step_up_needs_csrf(db, boss):
    assert boss.post("/me/step-up", {"code": totp_for(db, boss.user.email)}, csrf=False).status_code == 403
