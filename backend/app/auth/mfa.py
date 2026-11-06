"""TOTP / recovery-code primitives (pyotp for TOTP, Fernet for secrets at rest)."""

import hashlib
import hmac
import secrets
import time
from typing import Optional

import pyotp
from cryptography.fernet import Fernet

from backend.app.config import settings

STEP_SECONDS = 30
RECOVERY_CODE_COUNT = 10
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I


def _fernet() -> Fernet:
    return Fernet(settings.MFA_ENCRYPTION_KEY.encode())


def new_secret() -> str:
    return pyotp.random_base32()  # 160 bits


def encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_secret(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


def provisioning_uri(secret: str, account: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=account, issuer_name=settings.MFA_ISSUER)


def match_totp(secret: str, code: str, last_used_step: Optional[int]) -> Optional[int]:
    """Return the matching time-step (±1 step for clock drift), or None.

    Steps at or before `last_used_step` are rejected so a code works only once.
    """
    code = code.strip().replace(" ", "")
    if not (len(code) == 6 and code.isdigit()):
        return None
    totp = pyotp.TOTP(secret)
    now_step = int(time.time()) // STEP_SECONDS
    matched = None
    for step in (now_step - 1, now_step, now_step + 1):  # check all: no early exit timing signal
        if hmac.compare_digest(totp.at(step * STEP_SECONDS), code) and (
            last_used_step is None or step > last_used_step
        ):
            matched = step
    return matched


def generate_recovery_codes() -> list[str]:
    """10 codes, 12 chars (60 bits) shown as XXXX-XXXX-XXXX."""
    out = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(_ALPHABET) for _ in range(12))
        out.append(f"{raw[0:4]}-{raw[4:8]}-{raw[8:12]}")
    return out


def normalise_recovery(code: str) -> str:
    return code.strip().replace("-", "").replace(" ", "").upper()


def hash_recovery(code: str) -> str:
    return hashlib.sha256(normalise_recovery(code).encode()).hexdigest()


def looks_like_totp(code: str) -> bool:
    c = code.strip().replace(" ", "")
    return len(c) == 6 and c.isdigit()
