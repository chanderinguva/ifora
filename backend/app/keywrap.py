"""Purpose-separated encryption of private signing keys at rest (IFORA-25).

Before this module OIDC and SAML signing keys were both encrypted with the one Fernet key `OIDC_KEY_ENCRYPTION_KEY`.
Now every purpose gets its own Fernet key derived with HKDF-SHA256 (`cryptography`), so a value wrapped for one purpose
does not decrypt under another purpose's key.

* Ciphertext is `v2:<purpose>:<fernet token>`. A value without that prefix is the legacy format (the raw
  `OIDC_KEY_ENCRYPTION_KEY` Fernet token) and is still readable (dual-read) until migration 0060 rewrites it.
* The master secret for a purpose is `<PURPOSE>_KEY_ENCRYPTION_KEY` when that setting exists and is set, else
  `OIDC_KEY_ENCRYPTION_KEY`. With a dedicated secret, compromise of the OIDC secret does not expose SAML keys; with only
  the fallback, the subkeys are separate but both still derive from one master secret.
* No key material or plaintext is ever logged or put in an exception message.
"""

import base64
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from backend.app.config import settings

PURPOSES = ("oidc", "saml")
PREFIX = "v2:"
_INFO = b"ifora/key-wrap/v2/"


class KeyWrapError(RuntimeError):
    """Configuration problem or undecryptable value. Messages never contain secrets."""


def _master(purpose: str) -> str:
    own = getattr(settings, f"{purpose.upper()}_KEY_ENCRYPTION_KEY", "") if purpose != "oidc" else ""
    key = own or settings.OIDC_KEY_ENCRYPTION_KEY
    if not key:
        raise KeyWrapError("OIDC_KEY_ENCRYPTION_KEY is not set")
    if key == settings.MFA_ENCRYPTION_KEY:
        raise KeyWrapError("the key-encryption key must differ from MFA_ENCRYPTION_KEY")
    if own and own == settings.OIDC_KEY_ENCRYPTION_KEY:
        raise KeyWrapError(f"{purpose.upper()}_KEY_ENCRYPTION_KEY must differ from OIDC_KEY_ENCRYPTION_KEY (leave it unset to derive a subkey)")
    return key


def dedicated_secret(purpose: str) -> bool:
    """True when the purpose has its own master secret rather than falling back to OIDC_KEY_ENCRYPTION_KEY."""
    return purpose == "oidc" or bool(getattr(settings, f"{purpose.upper()}_KEY_ENCRYPTION_KEY", ""))


def subkey(purpose: str) -> Fernet:
    if purpose not in PURPOSES:
        raise KeyWrapError(f"unknown key purpose {purpose!r}")
    master = _master(purpose)
    try:
        Fernet(master.encode())  # must be a valid Fernet key, the same rule as before
    except ValueError as e:
        raise KeyWrapError("the key-encryption key is not a valid Fernet key") from e
    okm = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_INFO + purpose.encode()).derive(master.encode())
    return Fernet(base64.urlsafe_b64encode(okm))


def legacy_fernet() -> Fernet:
    """The pre-IFORA-25 key: OIDC_KEY_ENCRYPTION_KEY used directly. Only for reading and for the downgrade."""
    try:
        return Fernet(_master("oidc").encode())
    except ValueError as e:
        raise KeyWrapError("the key-encryption key is not a valid Fernet key") from e


def is_wrapped(value: str, purpose: Optional[str] = None) -> bool:
    return value.startswith(PREFIX if purpose is None else f"{PREFIX}{purpose}:")


def wrap(purpose: str, plaintext: bytes) -> str:
    return f"{PREFIX}{purpose}:" + subkey(purpose).encrypt(plaintext).decode()


def unwrap(purpose: str, value: str) -> bytes:
    """Decrypt `value` for `purpose`. A v2 value must carry this purpose's tag; a value without a tag is legacy."""
    try:
        if value.startswith(PREFIX):
            tag, _, token = value[len(PREFIX):].partition(":")
            if tag != purpose:
                raise KeyWrapError("this value was wrapped for a different purpose")
            return subkey(purpose).decrypt(token.encode())
        return legacy_fernet().decrypt(value.encode())
    except InvalidToken as e:
        raise KeyWrapError("cannot decrypt the key (wrong key-encryption key?)") from e
