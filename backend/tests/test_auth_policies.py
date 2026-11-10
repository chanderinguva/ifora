"""Network zones and per-application authentication policies (ADR 013)."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from cryptography.fernet import Fernet

from backend.app import ratelimit
from backend.app.config import settings
from backend.app.policies import engine
from backend.app.policies.models import NetworkZone
from tests.conftest import Api, make_user
from tests.test_oidc_authorize import CB, authorize, mk, params
from tests.test_swa import member_with_app


@pytest.fixture(autouse=True)
def swa_key(monkeypatch):
    monkeypatch.setattr(settings, "SWA_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "SWA_ENCRYPTION_KEY_PREVIOUS", "")


def at_ip(monkeypatch, ip):
    monkeypatch.setattr(ratelimit, "client_ip", lambda request: ip)


def zone(sa, name, *cidrs):
    r = sa.post("/admin/network-zones", {"name": name, "cidrs": list(cidrs)})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ---- zones -----------------------------------------------------------------------------------------------------------

def test_zone_crud_validation_and_access(super_admin, member):
    zid = zone(super_admin, "Office", "10.0.0.0/8", "192.168.1.5")
    assert super_admin.get("/admin/network-zones").json()["items"][0]["cidrs"] == ["10.0.0.0/8", "192.168.1.5/32"]
    assert super_admin.post("/admin/network-zones", {"name": "Office", "cidrs": ["10.1.0.0/16"]}).status_code == 409
    for bad in (["not-an-ip"], ["10.0.0.0/33"], []):
        assert super_admin.post("/admin/network-zones", {"name": "Bad", "cidrs": bad}).status_code == 422
    assert super_admin.put(f"/admin/network-zones/{zid}", {"name": "HQ", "cidrs": ["172.16.0.0/12"]}).json()["name"] == "HQ"
    assert member.get("/admin/network-zones").status_code == 403
    assert member.post("/admin/network-zones", {"name": "x", "cidrs": ["10.0.0.0/8"]}).status_code == 403
    assert super_admin.delete(f"/admin/network-zones/{zid}").status_code == 204
    assert super_admin.delete(f"/admin/network-zones/{zid}").status_code == 404


def test_zone_changes_are_audited(super_admin):
    zid = zone(super_admin, "Audited", "10.0.0.0/8")
    super_admin.delete(f"/admin/network-zones/{zid}")
    actions = {e["action"] for e in super_admin.get("/admin/audit?count=50").json()["Resources"]}
    assert {"NETWORK_ZONE_CREATED", "NETWORK_ZONE_DELETED"} <= actions


def test_zone_in_use_cannot_be_deleted(db, super_admin):
    app_id, _, _ = member_with_app(db, super_admin)
    zid = zone(super_admin, "Only", "10.0.0.0/8")
    assert super_admin.put(f"/admin/applications/{app_id}/policy", {"allowed_zone_ids": [zid]}).status_code == 200
    assert super_admin.delete(f"/admin/network-zones/{zid}").status_code == 409
    super_admin.delete(f"/admin/applications/{app_id}/policy")
    assert super_admin.delete(f"/admin/network-zones/{zid}").status_code == 204


# ---- policy configuration --------------------------------------------------------------------------------------------

def test_policy_defaults_validation_and_removal(db, super_admin, member):
    app_id, _, _ = member_with_app(db, super_admin)
    assert super_admin.get(f"/admin/applications/{app_id}/policy").json() == {
        "configured": False, "require_mfa": False, "reauth_minutes": None, "allowed_zone_ids": [], "blocked_zone_ids": []}
    z = zone(super_admin, "Z", "10.0.0.0/8")
    ok = super_admin.put(f"/admin/applications/{app_id}/policy", {"require_mfa": True, "reauth_minutes": 30, "blocked_zone_ids": [z]})
    assert ok.status_code == 200 and ok.json()["configured"] is True and ok.json()["blocked_zone_ids"] == [z]
    assert super_admin.put(f"/admin/applications/{app_id}/policy", {"reauth_minutes": 3}).status_code == 422
    assert super_admin.put(f"/admin/applications/{app_id}/policy", {"reauth_minutes": 5000}).status_code == 422
    assert super_admin.put(f"/admin/applications/{app_id}/policy", {"allowed_zone_ids": [99999]}).status_code == 400
    assert super_admin.put(f"/admin/applications/{app_id}/policy", {"allowed_zone_ids": [z], "blocked_zone_ids": [z]}).status_code == 400
    assert member.put(f"/admin/applications/{app_id}/policy", {}).status_code == 403
    assert super_admin.delete(f"/admin/applications/{app_id}/policy").status_code == 204
    assert super_admin.get(f"/admin/applications/{app_id}/policy").json()["configured"] is False


def test_policy_only_for_sso_applications(super_admin):
    b = super_admin.post("/admin/applications", {"name": "Link", "sign_on_mode": "bookmark", "launch_url": "https://example.com/"}).json()
    assert super_admin.put(f"/admin/applications/{b['id']}/policy", {"require_mfa": True}).status_code == 400
    assert super_admin.get("/admin/applications/999999/policy").status_code == 404


# ---- enforcement at SWA launch ---------------------------------------------------------------------------------------

def test_allowed_zone_gates_launch(monkeypatch, db, super_admin):
    app_id, _, m = member_with_app(db, super_admin)
    z = zone(super_admin, "Office", "10.0.0.0/8")
    super_admin.put(f"/admin/applications/{app_id}/policy", {"allowed_zone_ids": [z]})
    at_ip(monkeypatch, "10.4.5.6")
    assert m.post(f"/swa/apps/{app_id}/launch").status_code == 409  # policy passed; only the stored credential is missing
    at_ip(monkeypatch, "203.0.113.9")
    r = m.post(f"/swa/apps/{app_id}/launch")
    assert r.status_code == 403 and "approved networks" in r.json()["detail"]
    at_ip(monkeypatch, "not-an-ip")
    assert m.post(f"/swa/apps/{app_id}/launch").status_code == 403  # fails closed


def test_blocked_zone_beats_allowed_and_is_audited(monkeypatch, db, super_admin):
    app_id, _, m = member_with_app(db, super_admin)
    office, bad = zone(super_admin, "Office", "10.0.0.0/8"), zone(super_admin, "Bad", "10.9.0.0/16")
    super_admin.put(f"/admin/applications/{app_id}/policy", {"allowed_zone_ids": [office], "blocked_zone_ids": [bad]})
    at_ip(monkeypatch, "10.9.1.1")
    r = m.post(f"/swa/apps/{app_id}/launch")
    assert r.status_code == 403 and "cannot be used from your network" in r.json()["detail"]
    ev = super_admin.get("/admin/audit?action=APPLICATION_POLICY_DENIED").json()["Resources"]
    assert ev and ev[0]["target_id"] == str(app_id)


def test_ipv4_mapped_ipv6_matches_ipv4_zone(monkeypatch, db, super_admin):
    app_id, _, m = member_with_app(db, super_admin)
    z = zone(super_admin, "Office", "10.0.0.0/8")
    super_admin.put(f"/admin/applications/{app_id}/policy", {"allowed_zone_ids": [z]})
    at_ip(monkeypatch, "::ffff:10.1.1.1")
    assert m.post(f"/swa/apps/{app_id}/launch").status_code == 409


def test_require_mfa_denies_a_user_without_a_second_factor(db, super_admin):
    app_id, _, m = member_with_app(db, super_admin)
    super_admin.put(f"/admin/applications/{app_id}/policy", {"require_mfa": True})
    r = m.post(f"/swa/apps/{app_id}/launch")
    assert r.status_code == 403 and "multi-factor" in r.json()["detail"]


def test_stale_login_asks_for_reauthentication_and_is_not_audited_as_denial(db, super_admin):
    from backend.app.auth.session import Session as AuthSession

    app_id, u, m = member_with_app(db, super_admin)
    super_admin.put(f"/admin/applications/{app_id}/policy", {"reauth_minutes": 5})
    assert m.post(f"/swa/apps/{app_id}/launch").status_code == 409  # fresh sign-in: allowed
    db.query(AuthSession).filter(AuthSession.user_id == u.id).update({"auth_time": datetime.now(timezone.utc) - timedelta(minutes=6)})
    db.commit()
    r = m.post(f"/swa/apps/{app_id}/launch")
    assert r.status_code == 403 and r.json()["detail"] == "reauthentication_required"
    assert super_admin.get("/admin/audit?action=APPLICATION_POLICY_DENIED").json()["totalResults"] == 0


# ---- the decision function on its own --------------------------------------------------------------------------------

def _ns(amr, minutes_old=0, factor=False):
    return (SimpleNamespace(has_second_factor=factor),
            SimpleNamespace(amr=amr, auth_time=datetime.now(timezone.utc) - timedelta(minutes=minutes_old)))


def test_engine_mfa_and_freshness_decisions(db, super_admin):
    app_id, _, _ = member_with_app(db, super_admin)
    super_admin.put(f"/admin/applications/{app_id}/policy", {"require_mfa": True, "reauth_minutes": 10})
    u, s = _ns(["pwd"], factor=True)
    assert engine.evaluate(db, app_id, u, s, "10.0.0.1").kind == engine.REAUTH       # has a factor, signed in without it
    u, s = _ns(["pwd"], factor=False)
    assert engine.evaluate(db, app_id, u, s, "10.0.0.1").kind == engine.DENY         # nothing to step up with
    u, s = _ns(["pwd", "otp", "mfa"], minutes_old=11, factor=True)
    assert engine.evaluate(db, app_id, u, s, "10.0.0.1").kind == engine.REAUTH       # strong but stale
    u, s = _ns(["pwd", "otp", "mfa"], minutes_old=2, factor=True)
    assert engine.evaluate(db, app_id, u, s, "10.0.0.1").kind == engine.ALLOW


def test_deleted_allow_zone_fails_closed(db, super_admin):
    app_id, _, _ = member_with_app(db, super_admin)
    z = zone(super_admin, "Gone", "10.0.0.0/8")
    super_admin.put(f"/admin/applications/{app_id}/policy", {"allowed_zone_ids": [z]})
    db.query(NetworkZone).filter(NetworkZone.id == z).delete()  # bypasses the API guard, e.g. direct DB edit
    db.commit()
    u, s = _ns(["pwd"])
    assert engine.evaluate(db, app_id, u, s, "10.1.1.1").kind == engine.DENY


# ---- enforcement at OIDC authorize -----------------------------------------------------------------------------------

def _oidc_app_id(sa, client):
    return [a for a in sa.get("/admin/applications").json()["items"] if a["oidc_client"] and a["oidc_client"]["client_id"] == client["client_id"]][0]["id"]


def test_oidc_authorize_applies_the_policy(monkeypatch, db, super_admin):
    u = make_user(db, "alice@example.com")
    api = Api()
    assert api.login(u.email).status_code == 200
    c = mk(super_admin, first_party=True)
    app_id = _oidc_app_id(super_admin, c)

    baseline = authorize(api, params(c))
    assert baseline.status_code == 303 and "code=" in baseline.headers["location"]  # no policy: single sign-on

    z = zone(super_admin, "Office", "10.0.0.0/8")
    super_admin.put(f"/admin/applications/{app_id}/policy", {"allowed_zone_ids": [z]})
    at_ip(monkeypatch, "203.0.113.9")
    denied = authorize(api, params(c))
    q = parse_qs(urlsplit(denied.headers["location"]).query)
    assert denied.headers["location"].startswith(CB) and q["error"] == ["access_denied"] and "code" not in q

    at_ip(monkeypatch, "10.2.3.4")
    # no second factor to step up with: refused, with a reason the user can act on
    super_admin.put(f"/admin/applications/{app_id}/policy", {"allowed_zone_ids": [z], "require_mfa": True})
    needs_mfa = parse_qs(urlsplit(authorize(api, params(c)).headers["location"]).query)
    assert needs_mfa["error"] == ["access_denied"] and "multi-factor" in needs_mfa["error_description"][0]

    # an old sign-in is sent back through sign-in instead; with prompt=none the client is told login_required
    from backend.app.auth.session import Session as AuthSession

    super_admin.put(f"/admin/applications/{app_id}/policy", {"allowed_zone_ids": [z], "reauth_minutes": 5})
    assert authorize(api, params(c)).status_code == 303 and "code=" in authorize(api, params(c)).headers["location"]  # still fresh
    db.query(AuthSession).filter(AuthSession.user_id == u.id).update({"auth_time": datetime.now(timezone.utc) - timedelta(minutes=6)})
    db.commit()
    stale = authorize(api, params(c))
    assert not stale.headers["location"].startswith(CB) and "code=" not in stale.headers["location"]
    none = parse_qs(urlsplit(authorize(api, params(c, prompt="none")).headers["location"]).query)
    assert none["error"] == ["login_required"]


# ---- enforcement at SAML response ------------------------------------------------------------------------------------

def test_saml_response_is_withheld_outside_the_allowed_network(monkeypatch, super_admin, member):
    from tests.test_applications import assign
    from tests.test_saml import saml_app

    aid, _ = saml_app(super_admin)
    assign(super_admin, {"id": aid}, user_id=member.user.id)
    z = zone(super_admin, "Office", "10.0.0.0/8")
    super_admin.put(f"/admin/applications/{aid}/policy", {"allowed_zone_ids": [z]})
    at_ip(monkeypatch, "10.0.0.7")
    assert member.post(f"/saml/apps/{aid}/respond").status_code == 200
    at_ip(monkeypatch, "198.51.100.4")
    r = member.post(f"/saml/apps/{aid}/respond")
    assert r.status_code == 403 and "saml_response" not in r.text
    super_admin.put(f"/admin/applications/{aid}/policy", {"reauth_minutes": 5})
    from datetime import datetime, timedelta, timezone

    from backend.app.auth.session import Session as AuthSession
    from backend.app.tenancy import tenant_session

    s = tenant_session()
    s.query(AuthSession).filter(AuthSession.user_id == member.user.id).update({"auth_time": datetime.now(timezone.utc) - timedelta(minutes=9)})
    s.commit()
    s.close()
    stale = member.post(f"/saml/apps/{aid}/respond")
    assert stale.status_code == 403 and stale.json()["detail"] == "reauthentication_required"
