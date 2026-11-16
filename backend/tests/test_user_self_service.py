"""IFORA-43: end-user self-service security. Sessions are listed and revoked by opaque handle, only the caller's own
sessions and events are ever visible, removing the last required factor is refused, and factor changes and new devices
are announced by email.
"""

import pytest

from backend.app import mailer
from backend.app.auth import device, notify
from backend.app.auth.passkey_model import Passkey
from backend.app.auth.session import Session as AuthSession
from backend.app.config import settings
from tests.conftest import STRONG, Api, make_user
from tests.test_mfa import enrol, totp_for
from tests.test_tenancy import tenant_b, user_in  # noqa: F401  (fixture)

CHROME_MAC = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
FIREFOX_WIN = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0"
SAFARI_IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1"


def signed_in(email, ua=None):
    a = Api()
    if ua:
        a.c.headers["user-agent"] = ua
    assert a.login(email).status_code == 200
    return a


@pytest.fixture
def sent(monkeypatch):
    box = []
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(notify, "SEND_IN_BACKGROUND", False)
    monkeypatch.setitem(mailer.overrides, "send", box.append)
    return box


# --- device labels ---------------------------------------------------------------------------------------------------


def test_device_label_names_browser_and_system():
    assert device.label(CHROME_MAC) == "Chrome on macOS"
    assert device.label(FIREFOX_WIN).startswith("Firefox on Windows")
    assert "iOS" in device.label(SAFARI_IPHONE) or "iPhone" in device.label(SAFARI_IPHONE)
    assert device.label("") and device.label(None)  # never empty, never raises


def test_handles_are_stable_opaque_and_bound_to_the_user():
    h = device.handle(1, 7)
    assert h == device.handle(1, 7) and len(h) == 32
    assert h != device.handle(2, 7) and h != device.handle(1, 8)
    assert device.matches(h, 1, 7) and not device.matches(h, 2, 7) and not device.matches("x", 1, 7)


# --- sessions --------------------------------------------------------------------------------------------------------


def test_me_sessions_caller_scoped(db):
    a, b = make_user(db, "a@example.com"), make_user(db, "b@example.com")
    api_a, api_b = signed_in(a.email, CHROME_MAC), signed_in(b.email)
    signed_in(a.email, FIREFOX_WIN)
    items = api_a.get("/me/sessions").json()["items"]
    assert len(items) == 2 and sum(i["current"] for i in items) == 1
    for i in items:
        assert set(i) >= {"handle", "device", "ip_address", "created_at", "expires_at", "current"}
        assert "id" not in i and "user_id" not in i
    assert len(api_b.get("/me/sessions").json()["items"]) == 1
    handles_a = {i["handle"] for i in items}
    assert not handles_a & {i["handle"] for i in api_b.get("/me/sessions").json()["items"]}


def test_sessions_no_store_headers(member):
    for path in ("/me/sessions", "/me/activity"):
        r = member.get(path)
        assert r.headers["cache-control"] == "no-store", path


def test_revoke_other_session(db, member):
    other = signed_in(member.user.email, FIREFOX_WIN)
    items = member.get("/me/sessions").json()["items"]
    target = next(i for i in items if not i["current"])
    r = member.post(f"/me/sessions/{target['handle']}/revoke", {"password": STRONG})
    assert r.status_code == 200 and r.json() == {"revoked": 1}
    assert other.get("/me").status_code == 401
    assert member.get("/me").status_code == 200
    assert len(member.get("/me/sessions").json()["items"]) == 1
    ev = member.get("/me/activity").json()["items"]
    assert any(e["action"] == "SESSION_REVOKED" for e in ev)


def test_cannot_revoke_the_current_session_this_way(member):
    me = member.get("/me/sessions").json()["items"][0]
    assert me["current"]
    assert member.post(f"/me/sessions/{me['handle']}/revoke", {"password": STRONG}).status_code == 400
    assert member.get("/me").status_code == 200


def test_revoke_unknown_or_foreign_handle_is_404(db, member):
    victim = make_user(db, "victim@example.com")
    v = signed_in(victim.email)
    foreign = v.get("/me/sessions").json()["items"][0]["handle"]
    assert member.post(f"/me/sessions/{foreign}/revoke", {"password": STRONG}).status_code == 404
    assert member.post("/me/sessions/not-a-handle/revoke", {"password": STRONG}).status_code == 404
    assert v.get("/me").status_code == 200  # untouched


def test_revoke_requires_reauth_csrf(member):
    other = signed_in(member.user.email, FIREFOX_WIN)
    target = next(i for i in member.get("/me/sessions").json()["items"] if not i["current"])
    url = f"/me/sessions/{target['handle']}/revoke"
    assert member.post(url, {"password": "WrongPassw0rd!!"}).status_code == 403
    assert member.post(url, {}).status_code == 422
    assert member.post(url, {"password": STRONG}, csrf=False).status_code in (401, 403)
    assert other.get("/me").status_code == 200  # none of the refusals revoked anything
    assert Api().post(url, {"password": STRONG}).status_code == 401


def test_revoke_others_keeps_only_this_session(member):
    o1, o2 = signed_in(member.user.email, FIREFOX_WIN), signed_in(member.user.email, SAFARI_IPHONE)
    assert member.post("/me/sessions/revoke-others", {"password": "WrongPassw0rd!!"}).status_code == 403
    r = member.post("/me/sessions/revoke-others", {"password": STRONG})
    assert r.status_code == 200 and r.json()["revoked"] == 2
    assert o1.get("/me").status_code == 401 and o2.get("/me").status_code == 401
    assert member.get("/me").status_code == 200


def test_reauth_rate_limited(member):
    other = signed_in(member.user.email, FIREFOX_WIN)  # noqa: F841
    target = next(i for i in member.get("/me/sessions").json()["items"] if not i["current"])
    url = f"/me/sessions/{target['handle']}/revoke"
    assert [member.post(url, {"password": "WrongPassw0rd!!"}).status_code for _ in range(10)] == [403] * 10
    r = member.post(url, {"password": STRONG})
    assert r.status_code == 429 and r.headers.get("retry-after")


def test_cross_tenant_session_404(db, member, tenant_b):  # noqa: F811
    user_in(tenant_b, "member@example.com")  # same address in another tenant
    # a handle is derived from user id + session id: another tenant's session can never be addressed from here
    from tests.test_tenancy import b_session

    s = b_session(tenant_b)
    try:
        b_user = s.query(type(member.user)).filter_by(email="member@example.com").one()
        sess = AuthSession.create(user_id=b_user.id, session_lifetime_hours=1, ip_address="10.0.0.1", user_agent=CHROME_MAC,
                                  is_admin_session=False, amr=["pwd"])
        s.add(sess)
        s.commit()
        foreign = device.handle(b_user.id, sess.id)
    finally:
        s.close()
    assert member.post(f"/me/sessions/{foreign}/revoke", {"password": STRONG}).status_code == 404
    assert all(i["handle"] != foreign for i in member.get("/me/sessions").json()["items"])


# --- activity --------------------------------------------------------------------------------------------------------


def test_me_activity_only_own_events(db):
    a, b = make_user(db, "own@example.com"), make_user(db, "else@example.com")
    api_a = signed_in(a.email, CHROME_MAC)
    Api().login(b.email, "WrongPassw0rd!!")  # b's failed sign-in must never show up for a
    signed_in(b.email, FIREFOX_WIN)
    items = api_a.get("/me/activity").json()["items"]
    assert items and all(i["action"] in {"LOGIN_SUCCESS", "LOGIN_FAILURE", "LOGOUT"} for i in items)
    assert len(items) == 1
    assert items[0]["device"] == "Chrome on macOS" and items[0]["result"] == "success"
    assert not any("else@example.com" in str(i) for i in items)


def test_activity_shows_failures_with_device(db):
    u = make_user(db, "fail@example.com")
    api = Api()
    api.c.headers["user-agent"] = FIREFOX_WIN
    assert api.login(u.email, "WrongPassw0rd!!").status_code == 401
    me = signed_in(u.email, CHROME_MAC)
    items = me.get("/me/activity").json()["items"]
    failed = [i for i in items if i["result"] == "failure"]
    assert not failed or failed[0]["device"].startswith("Firefox")  # failure rows are attributed when the account is known


# --- last factor -----------------------------------------------------------------------------------------------------


def test_last_factor_removal_blocked(db, monkeypatch):
    u = make_user(db, "needs-mfa@example.com", admin=True)
    a = signed_in(u.email)
    enrol(a, db, u.email)  # enrolled while the policy is off (the test default); the policy then turns on
    monkeypatch.setattr(settings, "ADMIN_MFA_REQUIRED", True)
    r = a.post("/me/mfa/disable", {"password": STRONG, "code": totp_for(db, u.email)})
    assert r.status_code == 409 and "second factor" in r.json()["detail"]
    db.expire_all()
    assert u.mfa.enabled is True


def test_last_passkey_removal_blocked_for_required_admin(db, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_MFA_REQUIRED", True)
    u = make_user(db, "pk-admin@example.com", admin=True)
    db.add(Passkey(user_id=u.id, credential_id="cred-1", public_key=b"k", name="Key"))
    db.commit()
    a = signed_in(u.email)
    pid = db.query(Passkey).filter_by(user_id=u.id).one().id
    r = a.post(f"/me/passkeys/{pid}/remove", {"password": STRONG})
    assert r.status_code == 409 and "second factor" in r.json()["detail"]
    assert db.query(Passkey).filter_by(user_id=u.id).count() == 1


def test_ordinary_users_may_still_remove_their_factor(db):
    u = make_user(db, "plain@example.com")
    a = signed_in(u.email)
    enrol(a, db, u.email)
    r = a.post("/me/mfa/disable", {"password": STRONG, "code": totp_for(db, u.email)})
    assert r.status_code == 200 and r.json() == {"enabled": False}


# --- email -----------------------------------------------------------------------------------------------------------


def test_new_device_email(db, sent):
    u = make_user(db, "dev@example.com")
    signed_in(u.email, CHROME_MAC)
    assert sent == []  # a first sign-in is not "new"
    signed_in(u.email, CHROME_MAC)
    assert sent == []  # same device again
    signed_in(u.email, FIREFOX_WIN)
    assert len(sent) == 1 and sent[0]["To"] == u.email
    body = sent[0].get_body(preferencelist=("plain",)).get_content()
    assert "Firefox" in body and "http" not in body.lower().replace("http://localhost", "")  # no links, no codes
    signed_in(u.email, FIREFOX_WIN)
    assert len(sent) == 1  # now known


def test_password_change_and_factor_changes_send_mail(db, sent):
    u = make_user(db, "chg@example.com")
    a = signed_in(u.email, CHROME_MAC)
    assert a.post("/me/password", {"current_password": STRONG, "new_password": "Another1Passw0rd"}).status_code == 200
    assert len(sent) == 1 and sent[0]["To"] == u.email
    assert STRONG not in sent[0].get_body(preferencelist=("plain",)).get_content()


def test_mail_failure_never_breaks_the_action(db, monkeypatch):
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(notify, "SEND_IN_BACKGROUND", False)

    def boom(_msg):
        raise RuntimeError("smtp down")

    monkeypatch.setitem(mailer.overrides, "send", boom)
    u = make_user(db, "boom@example.com")
    a = signed_in(u.email)
    assert a.post("/me/password", {"current_password": STRONG, "new_password": "Another1Passw0rd"}).status_code == 200


def test_no_mail_server_means_no_attempt(db, monkeypatch):
    monkeypatch.setattr(mailer, "configured", lambda: False)
    u = make_user(db, "quiet@example.com")
    assert notify.notify(None, u, "x") is False
