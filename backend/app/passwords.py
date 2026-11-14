"""Argon2id password and client-secret hashing (IFORA-54).

Uses argon2-cffi directly (passlib is unmaintained). Parameters are pinned here (RFC 9106 "low memory" profile: 64 MiB,
3 passes, 4 lanes; the same values passlib used through argon2-cffi), so a library upgrade cannot change them silently.
Raise them here to strengthen new hashes; `needs_rehash` then flags older ones and a successful login upgrades them.

Stored hashes are the standard PHC string (`$argon2id$v=19$m=...`), so every hash written by passlib still verifies.
"""
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError

TIME_COST = 3
MEMORY_COST_KIB = 65536
PARALLELISM = 4

_hasher = PasswordHasher(
    time_cost=TIME_COST, memory_cost=MEMORY_COST_KIB, parallelism=PARALLELISM, hash_len=32, salt_len=16, type=Type.ID
)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, stored_hash: str | None) -> bool:
    """True only for a matching Argon2 hash. A mismatch, a malformed or empty hash, or a non-Argon2 value is False."""
    if not isinstance(stored_hash, str) or not stored_hash:
        return False
    try:
        return _hasher.verify(stored_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    """True when the hash was made with other parameters (or another Argon2 variant) than the current ones."""
    try:
        return _hasher.check_needs_rehash(stored_hash)
    except InvalidHashError:
        return False


# Verified against when the account/client does not exist, so response time does not reveal which exist.
DUMMY_HASH = hash_password("dummy-password-for-timing-equalisation")


def burn(password: str) -> None:
    """Spend one Argon2 verification (timing equalisation)."""
    verify_password(password, DUMMY_HASH)
