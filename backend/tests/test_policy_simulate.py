"""IFORA-33: policy simulation judges a hypothetical sign-in with the real engine and changes nothing."""

import pytest
from sqlalchemy import func, select

from backend.app import ratelimit
from backend.app.audit.model import AuditAction, AuditEvent
from backend.app.config import settings
from backend.app.policies import engine
from backend.app.policies.models import AppAuthPolicy
from tests.conftest import Api, make_user
from tests.test_auth_policies import zone
from tests.test_swa import member_with_app
from tests.test_tenancy import b_session, tenant_b  # noqa: F401  (fixture)

INSIDE, OUTSIDE = "203.0.113.9", "198.51.100.7"


@pytest.fixture
def world(db, super_admin):
    app_id, user, _ = member_with_app(db, super_admin)
    office = zone(super_admin, "Office", "203.0.113.0/24")
    assert super_admin.put(f"/admin/applications/{app_id}/policy", {"allowed_zone_ids": [office]}).status_code == 200
    return {"sa": super_admin, "app": app_id, "user": user, "office": office}


def sim(w, **over):
    body = {"user_id": w["user"].id, "source_ip": INSIDE, **over}
    return w["sa"].post(f"/admin/applications/{w['app']}/policy/simulate", body)


def audit_count(db):
    db.expire_all()
    return db.scalar(select(func.count()).select_from(AuditEvent))


def test_an_address_outside_the_allowed_zone_is_denied_without_any_audit_or_write(db, world):
    before = audit_count(db)
    r = sim(world, source_ip=OUTSIDE)
    assert r.status_code == 200, r.text
    st = r.json()["stored"]
    assert st["decision"] == "deny" and st["rule"] == "allowed_zones" and "approved networks" in st["reason"] and st["explanation"]
    assert audit_count(db) == before
    assert db.query(AuditEvent).filter(AuditEvent.action == AuditAction.APPLICATION_POLICY_DENIED).count() == 0


def test_an_address_inside_the_zone_is_allowed(world):
    st = sim(world).json()["stored"]
    assert st["decision"] == "allow" and st["rule"] == "passed"


def test_a_draft_is_judged_while_the_stored_policy_is_untouched(db, world):
    r = sim(world, policy={"require_mfa": True, "allowed_zone_ids": [world["office"]]})
    j = r.json()
    assert j["stored"]["decision"] == "allow"
    assert j["draft"]["decision"] in ("deny", "reauth") and j["draft"]["rule"] == "require_mfa"
    assert j["changed"] is True and j["draft_policy"]["require_mfa"] is True
    db.expire_all()
    stored = db.query(AppAuthPolicy).one()
    assert stored.require_mfa is False and stored.allowed_zone_ids == [world["office"]]  # nothing saved


def test_a_draft_that_changes_nothing_is_reported_as_unchanged(world):
    j = sim(world, policy={"allowed_zone_ids": [world["office"]]}).json()
    assert j["changed"] is False


def test_blocked_zone_wins_and_mfa_and_stale_rules_explain_themselves(db, world):
    sa, app = world["sa"], world["app"]
    bad = zone(sa, "Bad", "198.51.100.0/24")
    d = sim(world, source_ip=OUTSIDE, policy={"blocked_zone_ids": [bad]}).json()["draft"]
    assert d["decision"] == "deny" and d["rule"] == "blocked_zone"
    # an MFA requirement: a sign-in without a second factor, for a user who has none, is denied with the enrolment message
    d = sim(world, policy={"require_mfa": True}).json()["draft"]
    assert d["decision"] == "deny" and "second factor" in d["reason"]
    assert sim(world, amr=["pwd", "otp", "mfa"], policy={"require_mfa": True}).json()["draft"]["decision"] == "allow"
    # a recent-sign-in requirement judged against the supplied session age
    stale = sim(world, session_age_minutes=45, policy={"reauth_minutes": 30}).json()["draft"]
    assert stale["decision"] == "reauth" and stale["rule"] == "reauth_minutes"
    assert sim(world, session_age_minutes=5, policy={"reauth_minutes": 30}).json()["draft"]["decision"] == "allow"


def test_it_calls_the_real_evaluate_never_a_copy(world, monkeypatch):
    calls = []
    real = engine.evaluate

    def spy(*a, **kw):
        calls.append((a, kw))
        return real(*a, **kw)

    monkeypatch.setattr(engine, "evaluate", spy)
    sim(world, policy={"require_mfa": True})
    assert len(calls) == 2  # the stored policy, then the draft


def test_inputs_are_validated(db, world):
    assert sim(world, source_ip="not-an-ip").status_code == 422
    assert sim(world, source_ip="10.0.0.1/8").status_code == 422
    assert sim(world, amr=["pwd", "sorcery"]).status_code == 422
    assert sim(world, session_age_minutes=-1).status_code == 422
    assert sim(world, user_id=999999).status_code == 404
    assert world["sa"].post("/admin/applications/999999/policy/simulate", {"user_id": world["user"].id, "source_ip": INSIDE}).status_code == 404
    assert sim(world, policy={"allowed_zone_ids": [424242]}).status_code == 400  # unknown zone in the draft
    assert sim(world, policy={"allowed_zone_ids": [world["office"]], "blocked_zone_ids": [world["office"]]}).status_code == 400


def test_it_needs_an_administrator_a_session_and_csrf(db, world, member):
    url = f"/admin/applications/{world['app']}/policy/simulate"
    body = {"user_id": world["user"].id, "source_ip": INSIDE}
    assert member.post(url, body).status_code == 403
    assert Api().post(url, body).status_code == 401
    assert world["sa"].post(url, body, csrf=False).status_code == 403


def test_a_read_only_administrator_cannot_simulate(db, world):
    ro = make_user(db, "ro@example.com", admin=True)
    assert world["sa"].put(f"/admin/roles/users/{ro.id}", {"roles": ["read_only_admin"]}).status_code == 200
    a = Api()
    a.login(ro.email)
    assert a.get(f"/admin/applications/{world['app']}/policy").status_code == 200
    assert a.post(f"/admin/applications/{world['app']}/policy/simulate", {"user_id": world["user"].id, "source_ip": INSIDE}).status_code == 403


def test_a_user_of_another_tenant_is_a_404(db, world, tenant_b):  # noqa: F811
    s = b_session(tenant_b)
    other = make_user(s, "b-user@example.com")
    s.close()
    assert sim(world, user_id=other.id).status_code == 404


def test_simulations_are_rate_limited(world, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_POLICY_SIMULATE", 2)
    assert sim(world).status_code == 200 and sim(world).status_code == 200
    assert sim(world).status_code == 429


def test_an_engine_failure_is_a_500_and_leaves_no_partial_write(db, world, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("engine down")

    monkeypatch.setattr(engine, "evaluate", boom)
    before = audit_count(db)
    with pytest.raises(RuntimeError):
        sim(world)
    assert audit_count(db) == before
    db.expire_all()
    assert db.query(AppAuthPolicy).one().allowed_zone_ids == [world["office"]]


def test_the_evaluate_contract_is_unchanged_for_live_callers(world):
    assert engine.Decision("allow") == engine.Decision("allow", rule="passed")  # `rule` is explanatory, not part of equality
