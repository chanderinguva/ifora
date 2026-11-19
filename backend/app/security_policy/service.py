"""Evaluate and apply the organization security policy. One place, so every password path behaves the same."""

import secrets
import string
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.app import passwords
from backend.app.config import settings
from backend.app.security_policy.models import OrgSecurityPolicy, PasswordHistory

SYMBOLS = "!@#$%^&*()-_=+[]{};:,.?/"
HISTORY_KEEP = 24


@dataclass(frozen=True)
class Policy:
    min_length: int = 12
    require_mixed_case: bool = True
    require_digit: bool = True
    require_symbol: bool = False
    no_user_info: bool = False
    history_count: int = 0
    max_age_days: int = 0
    max_failed_attempts: int = 5
    lockout_minutes: int = 15
    session_lifetime_hours: int = 8
    idle_timeout_minutes: int = 30
    email_otp_members: str = "off"  # off | allowed
    email_otp_admins: str = "off"  # off | allowed | required
    push_members: str = "off"  # off | allowed
    push_admins: str = "off"  # off | allowed | required

    def as_dict(self) -> dict:
        return asdict(self)


FIELDS = tuple(Policy.__dataclass_fields__)


def defaults() -> Policy:
    """Built-in values: exactly the behaviour before the policy was configurable."""
    return Policy(max_failed_attempts=settings.MAX_LOGIN_ATTEMPTS, lockout_minutes=settings.LOGIN_LOCKOUT_MINUTES,
                  session_lifetime_hours=settings.SESSION_LIFETIME_HOURS, idle_timeout_minutes=settings.SESSION_IDLE_TIMEOUT_MINUTES)


def get(db: Session) -> Policy:
    row = db.query(OrgSecurityPolicy).first()
    if row is None:
        return defaults()
    return Policy(**{f: getattr(row, f) for f in FIELDS})


def rules(p: Policy) -> List[str]:
    """Human-readable rules, shown next to every password field."""
    out = [f"At least {p.min_length} characters"]
    if p.require_mixed_case:
        out.append("Upper and lower case letters")
    if p.require_digit:
        out.append("At least one digit")
    if p.require_symbol:
        out.append("At least one symbol")
    if p.no_user_info:
        out.append("Must not contain your name or the first part of your email")
    if p.history_count:
        out.append(f"Cannot reuse your last {p.history_count} password{'s' if p.history_count > 1 else ''}")
    return out


def _problems(p: Policy, password: str, email: Optional[str], first: Optional[str], last: Optional[str]) -> List[str]:
    out = []
    if len(password) < p.min_length:
        out.append(f"at least {p.min_length} characters")
    if p.require_mixed_case and (password.lower() == password or password.upper() == password):
        out.append("upper and lower case letters")
    if p.require_digit and not any(c.isdigit() for c in password):
        out.append("a digit")
    if p.require_symbol and not any(not c.isalnum() and not c.isspace() for c in password):
        out.append("a symbol")
    if p.no_user_info:
        low = password.lower()
        parts = [(email or "").split("@")[0], first or "", last or ""]
        if any(len(x) >= 3 and x.lower() in low for x in parts):
            out.append("no part of your name or email")
    return out


def validate_new(db: Session, password: str, user=None, email: Optional[str] = None, first: Optional[str] = None, last: Optional[str] = None) -> None:
    """Raise 422 unless the password satisfies the policy. Mutates nothing, so callers can check before consuming a token."""
    p = get(db)
    if user is not None:
        email, first, last = email or user.email, first or user.first_name, last or user.last_name
    bad = _problems(p, password, email, first, last)
    if bad:
        raise HTTPException(status_code=422, detail="Password needs: " + "; ".join(bad))
    if user is not None and p.history_count > 0:
        hashes = [user.password_hash]
        hashes += [h for (h,) in db.query(PasswordHistory.password_hash).filter(PasswordHistory.user_id == user.id)
                   .order_by(PasswordHistory.id.desc()).limit(max(p.history_count - 1, 0)).all()]
        for h in hashes:
            if passwords.verify_password(password, h):
                raise HTTPException(status_code=422, detail=f"You cannot reuse any of your last {p.history_count} password{'s' if p.history_count > 1 else ''}")


def apply_new(db: Session, user, password: str) -> None:
    """Store the new password (already validated): remember the old hash, stamp the change time."""
    p = get(db)
    if p.history_count > 0:
        db.add(PasswordHistory(user_id=user.id, password_hash=user.password_hash))
        db.flush()
        stale = [i for (i,) in db.query(PasswordHistory.id).filter(PasswordHistory.user_id == user.id).order_by(PasswordHistory.id.desc()).offset(HISTORY_KEEP).all()]
        if stale:
            db.query(PasswordHistory).filter(PasswordHistory.id.in_(stale)).delete(synchronize_session=False)
    user.set_password(password)


def set_checked(db: Session, user, password: str) -> None:
    validate_new(db, password, user)
    apply_new(db, user, password)


def generate(db: Session) -> str:
    """Random password that satisfies the current policy (used for admin-generated temporary passwords)."""
    p = get(db)
    for _ in range(50):
        n = max(20, p.min_length + 4)
        alphabet = string.ascii_letters + string.digits + (SYMBOLS if p.require_symbol else "")
        pw = "".join(secrets.choice(alphabet) for _ in range(n))
        if p.require_symbol:
            pw = pw[:-1] + secrets.choice(SYMBOLS)
        if not _problems(p, pw, None, None, None):
            return pw
    raise HTTPException(status_code=500, detail="Could not generate a password")


def expired_by_age(p: Policy, user, now: Optional[datetime] = None) -> bool:
    if not p.max_age_days:
        return False
    changed = user.password_changed_at or user.created_at
    if changed is None:
        return False
    if changed.tzinfo is None:
        changed = changed.replace(tzinfo=timezone.utc)
    return (now or datetime.now(timezone.utc)) - changed > timedelta(days=p.max_age_days)
