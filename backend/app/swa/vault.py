"""Credential vault: AES-256-GCM (cryptography) with a key derived by HKDF from SWA_ENCRYPTION_KEY.

The ciphertext is bound (AAD) to tenant, application and user, so a row copied to another user or application does not
decrypt. The key is separate from every other key in the system. A previous key may stay configured to read old rows
while they are lazily re-encrypted. Nothing is stored or logged in clear; with no key configured the vault refuses.
"""

import base64
import hashlib
import os
from typing import Optional, Tuple

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from backend.app.config import settings

_INFO = b"identityforge-swa-vault-v1"


class VaultUnavailable(Exception):
    """No (valid) SWA_ENCRYPTION_KEY: stored credentials cannot be written or read."""


class VaultError(Exception):
    """The stored secret cannot be decrypted (wrong key, or the row was moved)."""


def _load(raw: str) -> Optional[Tuple[str, bytes]]:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        material = base64.urlsafe_b64decode(raw.encode())
    except Exception:
        raise VaultUnavailable("SWA_ENCRYPTION_KEY is not valid base64")
    if len(material) != 32:
        raise VaultUnavailable("SWA_ENCRYPTION_KEY must be 32 random bytes, url-safe base64 encoded")
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_INFO).derive(material)
    return hashlib.sha256(key).hexdigest()[:8], key


def available() -> bool:
    try:
        return _load(settings.SWA_ENCRYPTION_KEY) is not None
    except VaultUnavailable:
        return False


def _current() -> Tuple[str, bytes]:
    cur = _load(settings.SWA_ENCRYPTION_KEY)
    if cur is None:
        raise VaultUnavailable("Stored sign-in credentials are not enabled on this server (SWA_ENCRYPTION_KEY is not set)")
    return cur


def _keys() -> dict:
    out = {}
    for raw in (settings.SWA_ENCRYPTION_KEY, settings.SWA_ENCRYPTION_KEY_PREVIOUS):
        k = _load(raw)
        if k:
            out[k[0]] = k[1]
    return out


def _aad(tenant_id: int, application_id: int, user_id: int) -> bytes:
    return f"swa:v1:{tenant_id}:{application_id}:{user_id}".encode()


def current_key_id() -> str:
    return _current()[0]


def encrypt(secret: str, tenant_id: int, application_id: int, user_id: int) -> Tuple[bytes, str]:
    key_id, key = _current()
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, secret.encode(), _aad(tenant_id, application_id, user_id))
    return nonce + ct, key_id


def decrypt(blob: bytes, key_id: str, tenant_id: int, application_id: int, user_id: int) -> str:
    key = _keys().get(key_id)
    if key is None:
        raise VaultError("The key that protected this credential is no longer configured")
    try:
        return AESGCM(key).decrypt(bytes(blob[:12]), bytes(blob[12:]), _aad(tenant_id, application_id, user_id)).decode()
    except (InvalidTag, ValueError):
        raise VaultError("The stored credential could not be decrypted")
