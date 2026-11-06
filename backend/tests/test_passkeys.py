"""Passkeys / WebAuthn: registration, usernameless sign-in, policy, abuse cases."""

import pytest
from webauthn.helpers import bytes_to_base64url

from backend.app.auth.passkey_model import Passkey, WebAuthnChallenge
from backend.app.config import settings
from backend.app.users.model import User
from tests.conftest import ORIGIN, STRONG, Api, make_user
from tests.fake_authenticator import FakeAuthenticator


def register(api, auth=None, name="Laptop", **kw):
    """Run the registration ceremony; returns (authenticator, response)."""
    auth = auth or FakeAuthenticator()
    o = api.post("/me/passkeys/register/options", {"password": STRONG})
    assert o.status_code == 200, o.text
    cred = auth.register(o.json()["options"], **kw)
    r = api.post("/me/passkeys/register/verify", {"ceremony_id": o.json()["ceremony_id"], "credential": cred, "name": name})
    return auth, r


def passkey_login(auth, expect=200, **kw):
    api = Api()
    o = api.c.post("/api/v1/login/passkey/options", headers={"Origin": ORIGIN})
    assert o.status_code == 200, o.text
    cred = auth.assertion(o.json()["options"], **kw)
    r = api.c.post(
        "/api/v1/login/passkey/verify",
        json={"ceremony_id": o.json()["ceremony_id"], "credential": cred},
        headers={"Origin": ORIGIN},
    )
    if r.status_code == 200:
        api.csrf = r.json()["csrf_token"]
    assert r.status_code == expect, r.text
    return api, r


@pytest.fixture
def pk(member):
    auth, r = register(member)
    assert r.status_code == 201, r.text
    member.auth = auth
    return member


# ---- registration ---------------------------------------------------------------

def test_registration_requires_password(member):
    assert member.post("/me/passkeys/register/options", {"password": "WrongPassw0rd!!"}).status_code == 403


def test_registration_options_demand_discoverable_uv_credentials(member, db):
    o = member.post("/me/passkeys/register/options", {"password": STRONG}).json()["options"]
    assert o["rp"]["id"] == "localhost"
    assert o["authenticatorSelection"]["residentKey"] == "required"
    assert o["authenticatorSelection"]["userVerification"] == "required"
    db.expire_all()
    handle = db.query(User).filter_by(email="member@example.com").one().webauthn_handle
    assert o["user"]["id"] == handle and "member" not in handle  # random handle, not PII


def test_register_and_list(pk, db):
    items = pk.get("/me/passkeys").json()["items"]
    assert len(items) == 1 and items[0]["name"] == "Laptop" and items[0]["transports"] == ["internal"]
    row = db.query(Passkey).one()
    assert row.credential_id == pk.auth.id and len(row.public_key) > 30
    assert pk.get("/me").json()["user"]["passkey_count"] == 1


def test_registration_ceremony_is_single_use(member):
    auth = FakeAuthenticator()
    o = member.post("/me/passkeys/register/options", {"password": STRONG}).json()
    cred = auth.register(o["options"])
    body = {"ceremony_id": o["ceremony_id"], "credential": cred, "name": "A"}
    assert member.post("/me/passkeys/register/verify", body).status_code == 201
    assert member.post("/me/passkeys/register/verify", body).status_code == 400  # replay


@pytest.mark.parametrize(
    "kw",
    [
        {"origin": "https://evil.example"},  # phishing site
        {"rp_id": "evil.example"},
        {"uv": False},  # no biometric / PIN
        {"challenge": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"},
    ],
)
def test_registration_rejects_bad_attestations(member, db, kw):
    _, r = register(member, **kw)
    assert r.status_code == 400
    assert db.query(Passkey).count() == 0


def test_registration_ceremony_bound_to_user(member, admin):
    auth = FakeAuthenticator()
    o = member.post("/me/passkeys/register/options", {"password": STRONG}).json()
    cred = auth.register(o["options"])
    r = admin.post("/me/passkeys/register/verify", {"ceremony_id": o["ceremony_id"], "credential": cred, "name": "x"})
    assert r.status_code == 400


def test_same_authenticator_cannot_be_registered_twice(pk):
    _, r = register(pk, auth=pk.auth)
    assert r.status_code == 400


def test_expired_ceremony_rejected(member, db):
    from datetime import datetime, timedelta, timezone

    auth = FakeAuthenticator()
    o = member.post("/me/passkeys/register/options", {"password": STRONG}).json()
    db.query(WebAuthnChallenge).update({"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)})
    db.commit()
    r = member.post("/me/passkeys/register/verify", {"ceremony_id": o["ceremony_id"], "credential": auth.register(o["options"]), "name": "x"})
    assert r.status_code == 400


# ---- sign in -------------------------------------------------------------------

def test_usernameless_passkey_login(pk, db):
    o = Api().c.post("/api/v1/login/passkey/options", headers={"Origin": ORIGIN}).json()["options"]
    assert "allowCredentials" not in o or not o["allowCredentials"]
    assert o["userVerification"] == "required"
    api, r = passkey_login(pk.auth)
    assert "identityforge_session" in r.headers["set-cookie"] and "HttpOnly" in r.headers["set-cookie"]
    assert r.json()["user"]["email"] == "member@example.com"
    assert api.get("/me").status_code == 200
    row = db.query(Passkey).one()
    assert row.sign_count == 1 and row.last_used_at is not None


def test_passkey_login_skips_totp_because_uv_is_already_mfa(pk, db):
    # enrol TOTP as well; passkey sign-in must not ask for it
    import pyotp

    s = pk.post("/me/mfa/setup", {"password": STRONG}).json()["secret"]
    assert pk.post("/me/mfa/enable", {"code": pyotp.TOTP(s).now()}).status_code == 200
    api, r = passkey_login(pk.auth)
    assert r.json()["success"] is True and "mfa_required" not in r.json()


def test_login_ceremony_single_use(pk):
    api = Api()
    o = api.c.post("/api/v1/login/passkey/options", headers={"Origin": ORIGIN}).json()
    cred = pk.auth.assertion(o["options"])
    body = {"ceremony_id": o["ceremony_id"], "credential": cred}
    assert api.c.post("/api/v1/login/passkey/verify", json=body, headers={"Origin": ORIGIN}).status_code == 200
    assert api.c.post("/api/v1/login/passkey/verify", json=body, headers={"Origin": ORIGIN}).status_code == 401


@pytest.mark.parametrize(
    "kw",
    [
        {"origin": "https://evil.example"},  # assertion produced on a look-alike site
        {"rp_id": "evil.example"},
        {"uv": False},
        {"user_handle": "AAAA"},  # handle of someone else
        {"challenge": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"},
    ],
)
def test_passkey_login_rejects_bad_assertions(pk, kw):
    passkey_login(pk.auth, expect=401, **kw)


def test_signature_from_another_key_rejected(pk):
    from cryptography.hazmat.primitives.asymmetric import ec

    passkey_login(pk.auth, expect=401, key=ec.generate_private_key(ec.SECP256R1()))


def test_unknown_credential_rejected():
    passkey_login(FakeAuthenticator(), expect=401, user_handle=None)


def test_counter_rollback_is_rejected_and_audited(pk, admin, db):
    passkey_login(pk.auth)  # counter 1
    passkey_login(pk.auth)  # counter 2
    passkey_login(pk.auth, expect=401, counter=1)  # cloned authenticator signature
    assert admin.get("/admin/audit?action=PASSKEY_COUNTER_ANOMALY").json()["total"] == 1


def test_inactive_user_cannot_use_passkey(pk, db):
    u = db.query(User).filter_by(email="member@example.com").one()
    u.status = "inactive"
    db.commit()
    passkey_login(pk.auth, expect=401)


def test_failed_passkey_logins_are_throttled(pk):
    for _ in range(settings.RATE_LIMIT_LOGIN_FAILURES):
        passkey_login(pk.auth, expect=401, origin="https://evil.example")
    api = Api()
    r = api.c.post("/api/v1/login/passkey/options", headers={"Origin": ORIGIN})
    assert r.status_code == 429


def test_passkey_login_rejects_foreign_origin_header(pk):
    r = Api().c.post("/api/v1/login/passkey/options", headers={"Origin": "http://evil.example"})
    assert r.status_code == 403


# ---- management ---------------------------------------------------------------------

def test_rename_and_remove_need_ownership(pk, admin):
    pid = pk.get("/me/passkeys").json()["items"][0]["id"]
    assert admin.patch(f"/me/passkeys/{pid}", {"name": "stolen"}).status_code == 404
    assert admin.post(f"/me/passkeys/{pid}/remove", {"password": STRONG}).status_code == 404
    assert pk.patch(f"/me/passkeys/{pid}", {"name": "Work Mac"}).json()["name"] == "Work Mac"


def test_remove_needs_password(pk):
    pid = pk.get("/me/passkeys").json()["items"][0]["id"]
    assert pk.post(f"/me/passkeys/{pid}/remove", {"password": "WrongPassw0rd!!"}).status_code == 403
    assert pk.post(f"/me/passkeys/{pid}/remove", {"password": STRONG}).status_code == 200
    assert pk.get("/me/passkeys").json()["items"] == []


def test_registered_passkey_cannot_be_used_after_removal(pk):
    pid = pk.get("/me/passkeys").json()["items"][0]["id"]
    pk.post(f"/me/passkeys/{pid}/remove", {"password": STRONG})
    passkey_login(pk.auth, expect=401)


def test_cascade_on_user_delete(pk, admin, db):
    assert admin.delete(f"/admin/users/{pk.user.id}").status_code == 200
    assert db.query(Passkey).count() == 0


# ---- "require a passkey" policy ----------------------------------------------------

def test_policy_needs_two_passkeys_and_password(pk):
    assert pk.post("/me/passkeys/policy", {"password": STRONG, "require": True}).status_code == 409
    register(pk, name="Phone")
    assert pk.post("/me/passkeys/policy", {"password": "WrongPassw0rd!!", "require": True}).status_code == 403
    assert pk.post("/me/passkeys/policy", {"password": STRONG, "require": True}).status_code == 200


def test_policy_blocks_password_logins_but_not_passkeys(pk, db):
    second, _ = register(pk, name="Phone")
    other = Api()
    other.login("member@example.com")
    assert pk.post("/me/passkeys/policy", {"password": STRONG, "require": True}).status_code == 200
    assert other.get("/me").status_code == 401  # password-era sessions are revoked
    assert pk.get("/me").status_code == 200  # the session that changed the policy survives

    r = Api().login("member@example.com")  # correct password
    assert r.status_code == 403 and "passkey" in r.json()["detail"].lower() and "set-cookie" not in r.headers
    # wrong password reveals nothing about the policy
    wrong = Api().login("member@example.com", "WrongPassw0rd!!")
    assert wrong.status_code == 401 and wrong.json()["detail"] == "Invalid credentials"
    passkey_login(pk.auth)
    passkey_login(second)


def test_policy_blocks_totp_path_too(pk):
    import pyotp

    register(pk, name="Phone")
    s = pk.post("/me/mfa/setup", {"password": STRONG}).json()["secret"]
    pk.post("/me/mfa/enable", {"code": pyotp.TOTP(s).now()})
    pk.post("/me/passkeys/policy", {"password": STRONG, "require": True})
    assert Api().login("member@example.com").status_code == 403


def test_cannot_drop_below_minimum_while_required(pk):
    register(pk, name="Phone")
    pk.post("/me/passkeys/policy", {"password": STRONG, "require": True})
    pid = pk.get("/me/passkeys").json()["items"][0]["id"]
    assert pk.post(f"/me/passkeys/{pid}/remove", {"password": STRONG}).status_code == 409
    pk.post("/me/passkeys/policy", {"password": STRONG, "require": False})
    assert pk.post(f"/me/passkeys/{pid}/remove", {"password": STRONG}).status_code == 200


def test_admin_reset_clears_passkeys_and_policy(pk, admin, db):
    register(pk, name="Phone")
    pk.post("/me/passkeys/policy", {"password": STRONG, "require": True})
    assert admin.post(f"/admin/users/{pk.user.id}/mfa/reset").status_code == 200
    assert db.query(Passkey).count() == 0
    assert Api().login("member@example.com").json()["success"] is True  # back to password login
    ev = admin.get("/admin/audit?action=MFA_RESET").json()["items"][0]
    assert ev["metadata"]["passkeys_removed"] == 2
