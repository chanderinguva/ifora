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
