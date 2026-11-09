"""Fixes for the Low findings of the independent review."""

from datetime import datetime, timedelta, timezone

from backend.app.auth import routes as auth_routes
from backend.app.config import settings
from tests.conftest import Api, STRONG, make_user
from tests.test_passkeys import passkey_login, register


def lock(db, user):
    db.expire_all()
    u = db.get(type(user), user.id)
    u.lockout_until = datetime.now(timezone.utc) + timedelta(minutes=15)
    db.commit()


def test_lockout_cannot_be_used_to_shut_the_owner_out(db):
    u = make_user(db, "owner@example.com")
    assert Api().login(u.email).status_code == 200            # signs in from this address, so it becomes a known one
    lock(db, u)                                                # someone elsewhere guessed wrongly until the account locked
    assert Api().login(u.email).status_code == 200            # the owner still gets in from the known address


def test_lockout_still_holds_from_an_unknown_address(db, monkeypatch):
    u = make_user(db, "owner2@example.com")
    lock(db, u)
    assert Api().login(u.email).status_code == 401            # never signed in from here
    monkeypatch.setattr(auth_routes, "is_known_ip", lambda *a: False)
    assert Api().login(u.email).status_code == 401


def test_wrong_passwords_from_a_known_address_do_not_extend_the_lockout(db):
    u = make_user(db, "owner3@example.com")
    Api().login(u.email)
    lock(db, u)
    before = db.get(type(u), u.id).lockout_until
    assert Api().login(u.email, "WrongPassw0rd!!").status_code == 401
    db.expire_all()
    assert db.get(type(u), u.id).lockout_until == before


def test_a_locked_account_cannot_sign_in_with_a_passkey(member, db):
    auth, r = register(member)
    assert r.status_code == 201, r.text
    lock(db, member.user)
    passkey_login(auth, expect=401)
    db.expire_all()
    db.get(type(member.user), member.user.id).lockout_until = None
    db.commit()
    passkey_login(auth)


def test_bootstrap_password_follows_the_password_policy(db):
    api = Api()
    body = {"email": "boss@example.com", "password": "Abcdef1!x", "first_name": "Boss", "last_name": "Person", "secret_key": settings.ADMIN_SECRET_KEY}
    r = api.c.post("/api/v1/admin/bootstrap", json=body)
    assert r.status_code == 422 and "Password needs" in r.json()["detail"]
    body["password"] = STRONG
    assert api.c.post("/api/v1/admin/bootstrap", json=body).status_code == 200
