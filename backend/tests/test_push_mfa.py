"""Push sign-in approval with number matching (IFORA-77): enrolment, the login round trip, wrong picks, expiry, device auth,
throttling, policy gating, reset, and the VAPID-signed delivery itself."""

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from joserfc import jwt
from joserfc.jwk import ECKey

from backend.app.auth import push_mfa
from backend.app.auth.mfa_model import PushChallenge, PushDevice
from backend.app.config import settings
from backend.app.users.model import User
from tests.conftest import ORIGIN, STRONG, Api, make_user

EP = "https://fcm.googleapis.com/fcm/send/"


class Woken(list):
    result: dict


@pytest.fixture
def pushed(monkeypatch):
    """A configured server whose push service accepts everything; `pushed` lists the endpoints that were woken."""
    priv, _ = push_mfa.new_vapid_key()
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", priv)
    monkeypatch.setattr(settings, "VAPID_SUBJECT", "mailto:ops@example.com")
    woken, result = Woken(), {"v": "ok"}
    monkeypatch.setitem(push_mfa.overrides, "send", lambda ep: (woken.append(ep), result["v"])[1])
    woken.result = result
    return woken


def set_policy(sa, **over):
    cur = sa.get("/admin/security-policy").json()["policy"]
    r = sa.put("/admin/security-policy", {**cur, **over})
    assert r.status_code == 200, r.text
    return r.json()


def add_device(api, name="Laptop", endpoint=EP + "abc", password=STRONG):
    return api.post("/me/mfa/push/devices", {"password": password, "name": name, "endpoint": endpoint})


@pytest.fixture
def enrolled(db, super_admin, pushed):
    """A person with one device. Returns (device auth header, email)."""
    set_policy(super_admin, push_members="allowed")
    u = make_user(db, "tap@example.com")
    a = Api()
    assert a.login(u.email).status_code == 200
    r = add_device(a)
    assert r.status_code == 201, r.text
    pushed.clear()
    return {"auth": f"Device {r.json()['id']}.{r.json()['secret']}", "email": u.email, "device_id": r.json()["id"]}


def step1(email="tap@example.com"):
    api = Api()
    r = api.login(email)
    assert r.status_code == 200 and r.json()["mfa_required"] is True, r.text
    return api, r.json()


def start(api, token):
    return api.c.post("/api/v1/login/mfa/push/start", json={"mfa_token": token}, headers={"Origin": ORIGIN})


def state(api, token):
    return api.c.post("/api/v1/login/mfa/push/status", json={"mfa_token": token}, headers={"Origin": ORIGIN})


def finish(api, token):
    r = api.c.post("/api/v1/login/mfa", json={"mfa_token": token, "code": "", "factor": "push"}, headers={"Origin": ORIGIN})
    if r.status_code == 200:
        api.csrf = r.json()["csrf_token"]
    return r


def pending(auth):
    return Api().c.get("/api/v1/device/push/pending", headers={"Authorization": auth})


def respond(auth, challenge_id, number):
    return Api().c.post("/api/v1/device/push/respond", json={"challenge_id": challenge_id, "number": number}, headers={"Authorization": auth, "Origin": ORIGIN})


# ---- policy and enrolment ---------------------------------------------------------------------------------------

def test_off_by_default_nobody_can_enrol(db, member, pushed):
    s = member.get("/me/mfa/push").json()
    assert s["allowed"] is False and s["configured"] is True and s["devices"] == []
    assert add_device(member).status_code == 403


def test_needs_vapid_keys(db, super_admin, member, monkeypatch):
    set_policy(super_admin, push_members="allowed")
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", "")
    assert member.get("/me/mfa/push").json()["public_key"] is None
    assert add_device(member).status_code == 503
    assert super_admin.put("/admin/security-policy", {**super_admin.get("/admin/security-policy").json()["policy"], "push_admins": "required"}).status_code == 422


def test_enrolment_checks_password_address_and_push_service(db, super_admin, member, pushed):
    set_policy(super_admin, push_members="allowed")
    assert add_device(member, password="WrongPassw0rd!!").status_code == 403
    for bad in ("http://fcm.googleapis.com/x", "https://evil.example.com/x", "https://fcm.googleapis.com.evil.com/x", "https://evilfcm.googleapis.com.evil.com/x",
                "https://user@fcm.googleapis.com/x", "https://fcm.googleapis.com:8443/x", "https://127.0.0.1/x", "javascript:alert(1)", "https://fcm.googleapis.com/" + "a" * 2100):
        assert add_device(member, endpoint=bad).status_code == 422, bad
    pushed.result["v"] = "failed"
    assert add_device(member).status_code == 400                                              # the push service refused the probe
    pushed.result["v"] = "ok"
    r = add_device(member)
    assert r.status_code == 201 and len(r.json()["secret"]) >= 40
    assert EP + "abc" in pushed                                                                 # the probe woke it
    d = db.query(PushDevice).one()
    assert r.json()["secret"] not in (d.secret_hash, d.endpoint) and len(d.secret_hash) == 64   # only a hash of the secret is kept
    assert add_device(member).status_code == 409                                              # same browser twice
    assert [x["name"] for x in member.get("/me/mfa/push").json()["devices"]] == ["Laptop"]
    assert "secret" not in str(member.get("/me/mfa/push").json())


def test_device_limit(db, super_admin, member, pushed):
    set_policy(super_admin, push_members="allowed")
    for i in range(push_mfa.MAX_DEVICES):
        assert add_device(member, endpoint=f"{EP}{i}").status_code == 201
    assert add_device(member, endpoint=EP + "one-too-many").status_code == 409


def test_remove_device_needs_the_password_and_audits(db, admin, super_admin, member, pushed):
    set_policy(super_admin, push_members="allowed")
    did = add_device(member).json()["id"]
    assert member.post(f"/me/mfa/push/devices/{did}/remove", {"password": "WrongPassw0rd!!"}).status_code == 403
    assert member.post(f"/me/mfa/push/devices/{did}/remove", {"password": STRONG}).json() == {"removed": True}
    assert member.post(f"/me/mfa/push/devices/{did}/remove", {"password": STRONG}).status_code == 404
    assert admin.get("/admin/audit?action=PUSH_DEVICE_ADDED").json()["totalResults"] == 1
    assert admin.get("/admin/audit?action=PUSH_DEVICE_REMOVED").json()["totalResults"] == 1


# ---- login ------------------------------------------------------------------------------------------------------

def test_login_with_push_approval_completes_and_is_not_recorded_as_mfa(db, enrolled, pushed):
    api, body = step1()
    assert body["factors"] == ["push"]
    s = start(api, body["mfa_token"])
    assert s.status_code == 200 and len(s.json()["number"]) == 2 and s.json()["expires_in"] == 90
    assert pushed == [EP + "abc"]                                                              # the device was woken, with no content
    assert state(api, body["mfa_token"]).json() == {"state": "pending"}
    assert finish(api, body["mfa_token"]).status_code == 409                                   # asking early is not an attempt
    p = pending(enrolled["auth"]).json()
    assert p["pending"] is True and len(p["choices"]) == 3 and len(set(p["choices"])) == 3 and s.json()["number"] in p["choices"]
    assert "number" not in p                                                                    # the device is never told which one
    assert respond(enrolled["auth"], p["challenge_id"], s.json()["number"]).json() == {"result": "approved"}
    assert state(api, body["mfa_token"]).json() == {"state": "approved"}
    r = finish(api, body["mfa_token"])
    assert r.status_code == 200, r.text
    from backend.app.auth.authn import acr_for
    from backend.app.auth.session import Session as AuthSession

    db.expire_all()
    amr = db.query(AuthSession).join(User, User.id == AuthSession.user_id).filter(User.email == "tap@example.com").order_by(AuthSession.id.desc()).first().amr
    assert amr == ["pwd", "swk"] and acr_for(amr).endswith(":1")                                # never an admin step-up proof, never acr 2
    assert finish(api, body["mfa_token"]).status_code == 401                                   # single use: the login challenge is gone


def test_an_approval_cannot_be_replayed_on_another_login(db, enrolled):
    api, body = step1()
    n = start(api, body["mfa_token"]).json()["number"]
    p = pending(enrolled["auth"]).json()
    respond(enrolled["auth"], p["challenge_id"], n)
    api2, body2 = step1()                                                                       # a second login for the same person
    assert finish(api2, body2["mfa_token"]).status_code == 401                                  # the approval belonged to the first login only
    assert finish(api, body["mfa_token"]).status_code == 401                                   # and a newer login replaced it


def test_wrong_number_fails_the_request_and_counts(db, admin, enrolled):
    api, body = step1()
    n = start(api, body["mfa_token"]).json()["number"]
    p = pending(enrolled["auth"]).json()
    bad = next(c for c in p["choices"] if c != n)
    assert respond(enrolled["auth"], p["challenge_id"], bad).json() == {"result": "denied"}
    assert state(api, body["mfa_token"]).json() == {"state": "denied"}
    db.expire_all()
    assert db.query(User).filter_by(email="tap@example.com").one().failed_login_attempts == 1   # counted like a wrong code
    assert finish(api, body["mfa_token"]).status_code == 401
    assert respond(enrolled["auth"], p["challenge_id"], n).status_code == 404                  # a dead request cannot be revived
    assert admin.get("/admin/audit?action=PUSH_DENIED").json()["totalResults"] == 1


def test_three_wrong_picks_block_new_requests(db, admin, enrolled):
    for _ in range(push_mfa.FAIL_LIMIT):
        api, body = step1()
        n = start(api, body["mfa_token"]).json()["number"]
        p = pending(enrolled["auth"]).json()
        respond(enrolled["auth"], p["challenge_id"], next(c for c in p["choices"] if c != n))
    api, body = step1()
    assert start(api, body["mfa_token"]).status_code == 429
    assert admin.get("/admin/audit?action=PUSH_LOCKED").json()["totalResults"] == 1


def test_this_was_not_me_ends_the_sign_in(db, enrolled):
    api, body = step1()
    start(api, body["mfa_token"])
    p = pending(enrolled["auth"]).json()
    assert respond(enrolled["auth"], p["challenge_id"], None).json() == {"result": "denied"}
    assert state(api, body["mfa_token"]).json() == {"state": "denied"}
    assert finish(api, body["mfa_token"]).status_code == 401
    assert start(api, body["mfa_token"]).status_code == 401                                    # the login itself is dead, start over from the password


def test_declines_also_block_new_requests(db, admin, enrolled):
    for _ in range(push_mfa.FAIL_LIMIT):
        api, body = step1()
        start(api, body["mfa_token"])
        respond(enrolled["auth"], pending(enrolled["auth"]).json()["challenge_id"], None)
    api, body = step1()
    assert start(api, body["mfa_token"]).status_code == 429                                    # prompt-bombing with a stolen password stops
    assert admin.get("/admin/audit?action=PUSH_LOCKED").json()["totalResults"] == 1
    db.expire_all()
    assert db.query(User).filter_by(email="tap@example.com").one().failed_login_attempts == 0   # declining is not the account's failure


def test_expired_request_is_refused(db, enrolled):
    api, body = step1()
    n = start(api, body["mfa_token"]).json()["number"]
    p = pending(enrolled["auth"]).json()
    row = db.query(PushChallenge).one()
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    assert state(api, body["mfa_token"]).json() == {"state": "expired"}
    assert pending(enrolled["auth"]).json() == {"pending": False}
    assert respond(enrolled["auth"], p["challenge_id"], n).status_code == 404
    assert finish(api, body["mfa_token"]).status_code == 401


def test_only_an_offered_number_is_accepted(db, enrolled):
    api, body = step1()
    n = start(api, body["mfa_token"]).json()["number"]
    p = pending(enrolled["auth"]).json()
    outside = next(f"{i:02d}" for i in range(10, 100) if f"{i:02d}" not in p["choices"])
    assert respond(enrolled["auth"], p["challenge_id"], outside).status_code == 422
    assert respond(enrolled["auth"], p["challenge_id"], "x1").status_code == 422
    assert respond(enrolled["auth"], p["challenge_id"], n).json() == {"result": "approved"}    # the failed tries did not use it up


# ---- the device itself ------------------------------------------------------------------------------------------

def test_a_device_must_prove_itself(db, enrolled):
    api, body = step1()
    start(api, body["mfa_token"])
    good = enrolled["auth"]
    bad_secret = good[: good.index(".") + 1] + "x" * 43
    for bad in (None, "", "Device", "Device abc", f"Device 999999.{'a' * 43}", bad_secret, "Bearer " + good[7:], good + "x"):
        r = Api().c.get("/api/v1/device/push/pending", headers={"Authorization": bad} if bad is not None else {})
        assert r.status_code == 401, bad
    assert pending(good).json()["pending"] is True


def test_another_persons_device_cannot_answer(db, super_admin, enrolled, pushed):
    other = make_user(db, "other@example.com")
    a = Api()
    a.login(other.email)
    r = add_device(a, endpoint=EP + "other")
    other_auth = f"Device {r.json()['id']}.{r.json()['secret']}"
    api, body = step1()
    n = start(api, body["mfa_token"]).json()["number"]
    cid = pending(enrolled["auth"]).json()["challenge_id"]
    assert pending(other_auth).json() == {"pending": False}
    assert respond(other_auth, cid, n).status_code == 404
    assert state(api, body["mfa_token"]).json() == {"state": "pending"}


def test_a_removed_device_can_no_longer_approve(db, enrolled):
    api, body = step1()
    start(api, body["mfa_token"])
    db.query(PushDevice).delete()
    db.commit()
    assert pending(enrolled["auth"]).status_code == 401


# ---- delivery ---------------------------------------------------------------------------------------------------

def test_unreachable_devices_fail_cleanly(db, enrolled, pushed):
    api, body = step1()
    pushed.result["v"] = "failed"
    assert start(api, body["mfa_token"]).status_code == 502
    assert db.query(PushChallenge).count() == 0
    pushed.result["v"] = "gone"                                                                  # the subscription was cancelled at the push service
    assert start(api, body["mfa_token"]).status_code == 502
    db.expire_all()
    assert db.query(PushDevice).count() == 0


def test_requests_are_limited_to_three_a_minute(db, enrolled):
    api, body = step1()
    assert [start(api, body["mfa_token"]).status_code for _ in range(3)] == [200, 200, 200]
    assert start(api, body["mfa_token"]).status_code == 429


def test_start_needs_a_live_login_and_an_allowed_factor(db, super_admin, enrolled):
    assert start(Api(), "nope").status_code == 401
    api, body = step1()
    set_policy(super_admin, push_members="off")                                                  # switched off: devices stop counting
    assert start(api, body["mfa_token"]).status_code == 401
    assert Api().login("tap@example.com").json().get("mfa_required") is not True


def test_vapid_delivery_is_signed_empty_and_audience_bound(monkeypatch):
    priv, pub = push_mfa.new_vapid_key()
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", priv)
    monkeypatch.setattr(settings, "VAPID_SUBJECT", "mailto:ops@example.com")
    seen, code = [], {"v": 201}

    def handler(req: httpx.Request):
        seen.append(req)
        return httpx.Response(code["v"])

    monkeypatch.setitem(push_mfa.overrides, "transport", httpx.MockTransport(handler))
    assert push_mfa.send("https://updates.push.services.mozilla.com/wpush/v2/abc") == "ok"
    req = seen[0]
    assert req.content == b"" and req.headers["ttl"] == "90" and req.headers["urgency"] == "high"
    scheme, _, rest = req.headers["authorization"].partition(" ")
    parts = dict(p.strip().split("=", 1) for p in rest.split(", "))
    assert scheme == "vapid" and parts["k"] == pub == push_mfa.public_key()
    from base64 import urlsafe_b64decode
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    point = urlsafe_b64decode(pub + "=" * (-len(pub) % 4))
    key = ECKey.import_key(ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), point).public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
    claims = jwt.decode(parts["t"], key).claims
    assert claims["aud"] == "https://updates.push.services.mozilla.com" and claims["sub"] == "mailto:ops@example.com"
    assert 0 < claims["exp"] - datetime.now(timezone.utc).timestamp() <= 12 * 3600
    code["v"] = 410
    assert push_mfa.send("https://fcm.googleapis.com/x") == "gone"
    code["v"] = 500
    assert push_mfa.send("https://fcm.googleapis.com/x") == "failed"
    code["v"] = 302                                                                              # redirects are never followed
    assert push_mfa.send("https://fcm.googleapis.com/x") == "failed" and len(seen) == 4


# ---- admins, reset ----------------------------------------------------------------------------------------------

def test_admin_reset_removes_devices(db, super_admin, enrolled):
    uid = db.query(User).filter_by(email="tap@example.com").one().id
    assert super_admin.post(f"/admin/users/{uid}/mfa/reset").status_code == 200
    db.expire_all()
    assert db.query(PushDevice).filter_by(user_id=uid).count() == 0
    assert pending(enrolled["auth"]).status_code == 401
    assert Api().login("tap@example.com").json().get("mfa_required") is not True


def test_required_for_admins_gates_admin_functions_until_a_device_exists(db, super_admin, admin, pushed):
    assert admin.get("/admin/users").status_code == 200
    set_policy(super_admin, push_admins="required")
    r = admin.get("/admin/users")
    assert r.status_code == 403 and "setup required" in r.json()["detail"]
    assert admin.get("/me").status_code == 200
    assert admin.get("/admin/security-policy").status_code == 200                                # an admin can always reach (and undo) the policy
    did = add_device(admin).json()["id"]
    assert admin.get("/admin/users").status_code == 200
    assert admin.post(f"/me/mfa/push/devices/{did}/remove", {"password": STRONG}).status_code == 409   # cannot opt out while required


def test_required_is_not_enforced_when_push_cannot_be_sent(db, super_admin, admin, pushed, monkeypatch):
    set_policy(super_admin, push_admins="required")
    assert admin.get("/admin/users").status_code == 403
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", "")
    assert admin.get("/admin/users").status_code == 200                                          # never lock admins out of a server that cannot push


def test_policy_omitted_fields_keep_their_value(db, super_admin):
    set_policy(super_admin, push_members="allowed")
    body = {k: v for k, v in super_admin.get("/admin/security-policy").json()["policy"].items() if not k.startswith("push_")}
    out = super_admin.put("/admin/security-policy", body).json()["policy"]
    assert out["push_members"] == "allowed" and out["push_admins"] == "off"
    assert super_admin.put("/admin/security-policy", {**body, "push_members": "required"}).status_code == 422
