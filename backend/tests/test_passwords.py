"""Argon2id hashing without passlib (IFORA-54): old hashes keep working, weaker ones are upgraded at login."""

from argon2 import PasswordHasher, Type

from backend.app import passwords
from backend.app.users.model import User
from tests.conftest import STRONG, Api, make_user

# Written by passlib 1.7.4 (argon2-cffi backend) before this change, for the password below.
PASSLIB_HASH = "$argon2id$v=19$m=65536,t=3,p=4$ea/VOiektNb6X4sR4vxfiw$Xsxtut+k5cYzhjRrIf26+0ktj6LaSUmCUejRt+tahAo"
PASSLIB_PASSWORD = "Legacy-Passw0rd!"
# Same PHC format with cheaper parameters, as an older deployment (or a lower passlib default) would have stored.
WEAK_HASHER = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1, type=Type.ID)


def test_new_hash_is_argon2id_with_current_parameters():
    h = passwords.hash_password(STRONG)
    assert h.startswith("$argon2id$v=19$m=65536,t=3,p=4$")
    assert passwords.verify_password(STRONG, h)
    assert not passwords.needs_rehash(h)
    assert passwords.hash_password(STRONG) != h  # random salt


def test_hash_written_by_passlib_still_verifies():
    assert passwords.verify_password(PASSLIB_PASSWORD, PASSLIB_HASH)
    assert not passwords.verify_password("Wrong-Passw0rd!", PASSLIB_HASH)
    assert not passwords.needs_rehash(PASSLIB_HASH)  # passlib already used the same parameters


def test_bad_or_foreign_hashes_never_verify_and_never_raise():
    for stored in (None, "", "not-a-hash", "$2b$12$abcdefghijklmnopqrstuuJ1pL8F1Xr0yQxQ7s1Yq3m8cE8w4m1Wy", "$argon2id$v=19$m=1$broken"):
        assert passwords.verify_password(STRONG, stored) is False
    assert passwords.needs_rehash("not-a-hash") is False


def test_weaker_parameters_are_flagged_for_rehash():
    weak = WEAK_HASHER.hash(STRONG)
    assert passwords.verify_password(STRONG, weak)
    assert passwords.needs_rehash(weak)
    argon2i = PasswordHasher(type=Type.I).hash(STRONG)
    assert passwords.needs_rehash(argon2i)  # variant other than argon2id is also upgraded


def test_passlib_user_can_log_in_and_hash_is_kept(db):
    u = make_user(db, "legacy@example.com")
    u.password_hash = PASSLIB_HASH
    db.commit()
    assert Api().login("legacy@example.com", PASSLIB_PASSWORD).status_code == 200
    db.expire_all()
    assert db.get(User, u.id).password_hash == PASSLIB_HASH  # parameters unchanged: no rewrite


def test_login_upgrades_a_weak_hash_without_counting_as_a_password_change(db):
    u = make_user(db, "weak@example.com")
    u.password_hash = WEAK_HASHER.hash(STRONG)
    db.commit()
    changed_at = u.password_changed_at

    assert Api().login("weak@example.com", STRONG).status_code == 200

    db.expire_all()
    u = db.get(User, u.id)
    assert u.password_hash.startswith("$argon2id$v=19$m=65536,t=3,p=4$")
    assert u.verify_password(STRONG)
    assert u.password_changed_at == changed_at  # password-age policy is untouched
    before = u.password_hash
    assert Api().login("weak@example.com", STRONG).status_code == 200
    db.expire_all()
    assert db.get(User, u.id).password_hash == before  # already current: not rewritten again


def test_failed_login_does_not_touch_a_weak_hash(db):
    u = make_user(db, "weak2@example.com")
    weak = WEAK_HASHER.hash(STRONG)
    u.password_hash = weak
    db.commit()
    assert Api().login("weak2@example.com", "Wrong-Passw0rd!!").status_code == 401
    db.expire_all()
    assert db.get(User, u.id).password_hash == weak
