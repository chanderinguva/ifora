"""MFA business logic shared by login, enrolment and admin routes."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.app.auth import mfa
from backend.app.auth.mfa_model import MFAChallenge, MFARecoveryCode, UserMFA
from backend.app.config import settings
from backend.app.users.model import User


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _h(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


# ---- login challenges -------------------------------------------------------

def issue_challenge(db: Session, user: User) -> str:
    """Create a fresh challenge (older ones for the user are discarded). Returns the raw token."""
    db.query(MFAChallenge).filter(MFAChallenge.user_id == user.id).delete(synchronize_session=False)
    raw = secrets.token_urlsafe(32)
    db.add(
        MFAChallenge(
            user_id=user.id,
            token_hash=_h(raw),
            expires_at=_now() + timedelta(minutes=settings.MFA_CHALLENGE_MINUTES),
        )
    )
    db.commit()
    return raw


def load_challenge(db: Session, raw: str) -> Optional[MFAChallenge]:
    if not raw or len(raw) > 128:
        return None
    ch = db.query(MFAChallenge).filter(MFAChallenge.token_hash == _h(raw)).first()
    if ch is None:
        return None
    if ch.expires_at < _now() or ch.attempts >= settings.MFA_CHALLENGE_MAX_ATTEMPTS:
        db.delete(ch)
        db.commit()
        return None
    return ch


def burn_challenge(db: Session, ch: MFAChallenge) -> None:
    db.delete(ch)
    db.commit()


# ---- second factor ----------------------------------------------------------

def verify_second_factor(db: Session, user: User, code: str) -> Optional[str]:
    """Check a TOTP or recovery code. Returns "totp", "recovery" or None. Does not commit.

    Both paths consume atomically (conditional UPDATE), so a code cannot be used twice
    even under concurrent requests.
    """
    record = user.mfa
    if record is None or not record.enabled or not code or len(code) > 64:
        return None
    if mfa.looks_like_totp(code):
        step = mfa.match_totp(mfa.decrypt_secret(record.secret_encrypted), code, record.last_used_step)
        if step is None:
            return None
        n = (
            db.query(UserMFA)
            .filter(UserMFA.id == record.id, or_(UserMFA.last_used_step.is_(None), UserMFA.last_used_step < step))
            .update({UserMFA.last_used_step: step}, synchronize_session=False)
        )
        return "totp" if n == 1 else None
    n = (
        db.query(MFARecoveryCode)
        .filter(
            MFARecoveryCode.user_id == user.id,
            MFARecoveryCode.code_hash == mfa.hash_recovery(code),
            MFARecoveryCode.used_at.is_(None),
        )
        .update({MFARecoveryCode.used_at: _now()}, synchronize_session=False)
    )
    return "recovery" if n == 1 else None


def replace_recovery_codes(db: Session, user: User) -> list[str]:
    """Invalidate all existing recovery codes and create a new set. Returns the plaintext codes (shown once)."""
    db.query(MFARecoveryCode).filter(MFARecoveryCode.user_id == user.id).delete(synchronize_session=False)
    codes = mfa.generate_recovery_codes()
    for c in codes:
        db.add(MFARecoveryCode(user_id=user.id, code_hash=mfa.hash_recovery(c)))
    return codes


def recovery_remaining(db: Session, user: User) -> int:
    return (
        db.query(MFARecoveryCode)
        .filter(MFARecoveryCode.user_id == user.id, MFARecoveryCode.used_at.is_(None))
        .count()
    )


def remove_mfa(db: Session, user: User) -> None:
    """Delete enrolment, recovery codes and pending challenges. Does not commit."""
    db.query(MFARecoveryCode).filter(MFARecoveryCode.user_id == user.id).delete(synchronize_session=False)
    db.query(MFAChallenge).filter(MFAChallenge.user_id == user.id).delete(synchronize_session=False)
    if user.mfa is not None:
        db.delete(user.mfa)
    if user.email_otp is not None:
        db.delete(user.email_otp)  # an admin reset (lost device) removes every extra factor
    for d in list(user.push_devices):
        db.delete(d)


def reset_all_factors(db: Session, user) -> dict:
    """Remove TOTP, recovery codes and passkeys, lift the passkey-required policy and end every
    session. Shared by the admin API and the recovery CLI. Caller records the audit event and commits."""
    from backend.app.auth.sessions_util import revoke_user_sessions

    passkeys_removed = len(user.passkeys)
    remove_mfa(db, user)
    for p in list(user.passkeys):
        db.delete(p)
    user.passkey_required = False
    return {"sessions_revoked": revoke_user_sessions(db, user.id), "passkeys_removed": passkeys_removed}


# ---- admin first-factor enrolment code --------------------------------------
# A password alone must not be enough for an admin to attach the first factor: whoever holds the
# password could otherwise enrol their own authenticator and satisfy ADMIN_MFA_REQUIRED.

ENROLLMENT_CODE_HOURS = 24
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no look-alikes


def _norm_code(raw: str) -> str:
    return "".join(ch for ch in (raw or "").upper() if ch.isalnum())


def issue_enrollment_code(user: User) -> str:
    """Create a new single-use code (replacing any older one). Returns it once; only a hash is kept."""
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(12))
    user.enrollment_code_hash = _h(raw)
    user.enrollment_code_expires_at = _now() + timedelta(hours=ENROLLMENT_CODE_HOURS)
    return f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"


def enrollment_code_ok(user: User, supplied: Optional[str]) -> bool:
    if not user.enrollment_code_hash or not user.enrollment_code_expires_at or not supplied:
        return False
    if user.enrollment_code_expires_at <= _now():
        return False
    return secrets.compare_digest(user.enrollment_code_hash, _h(_norm_code(supplied)))


def consume_enrollment_code(user: User, supplied: Optional[str]) -> bool:
    """Check the code and spend it in one conditional UPDATE: of two concurrent requests with the same code, one wins.
    Does not commit; the caller's transaction decides (a refused request rolls the spend back)."""
    from sqlalchemy.orm import object_session

    if not enrollment_code_ok(user, supplied):
        return False
    db = object_session(user)
    n = (
        db.query(User)
        .filter(User.id == user.id, User.enrollment_code_hash == user.enrollment_code_hash)
        .update({User.enrollment_code_hash: None, User.enrollment_code_expires_at: None}, synchronize_session=False)
    )
    if n != 1:
        return False
    user.enrollment_code_hash = None
    user.enrollment_code_expires_at = None
    return True


def clear_enrollment_code(user: User) -> None:
    user.enrollment_code_hash = None
    user.enrollment_code_expires_at = None
