"""Email one-time code (OTP) second factor (IFORA-60).

Rules: a 6-digit code from the OS CSPRNG, valid 5 minutes, spent on first success; 3 wrong tries destroy it and block a new one for a
cooldown; only a keyed hash is stored; the code goes only to the account's own address. Request throttling (3 per minute per user
and per IP) is applied by the routes, which hold the request.
"""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from backend.app import mailer
from backend.app.auth.mfa_model import UserEmailOTP
from backend.app.config import settings
from backend.app.security_policy import service as sec_policy
from backend.app.users.model import User

CODE_TTL_SECONDS = 300
MAX_ATTEMPTS = 3
COOLDOWN_MINUTES = 15
SEND_LIMIT = 3  # requests per SEND_WINDOW_SECONDS, per user and per IP
SEND_WINDOW_SECONDS = 60


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _digest(user_id: int, code: str) -> str:
    """Keyed, so a leaked database cannot be brute-forced offline across the 10^6 code space."""
    return hmac.new(settings.SECRET_KEY.encode(), f"email-otp:{user_id}:{code}".encode(), hashlib.sha256).hexdigest()


def generate() -> str:
    return f"{secrets.randbelow(10**6):06d}"


def audience_policy(db: Session, user: User) -> str:
    p = sec_policy.get(db)
    return p.email_otp_admins if user.is_admin else p.email_otp_members


def allowed(db: Session, user: User) -> bool:
    """The organisation policy lets this user use the factor at all (off by default)."""
    return audience_policy(db, user) in ("allowed", "required")


def required_but_missing(db: Session, user: User) -> bool:
    """Administrators only: the policy mandates the factor and this admin has not enrolled it."""
    return bool(user.is_admin and mailer.configured() and audience_policy(db, user) == "required" and not is_enabled(user))  # never lock admins out when no mail can be sent


def is_enabled(user: User) -> bool:
    return bool(user.email_otp is not None and user.email_otp.enabled)


def usable_at_login(db: Session, user: User) -> bool:
    return is_enabled(user) and allowed(db, user)


def login_factors(db: Session, user: User) -> List[str]:
    out = []
    if user.mfa is not None and user.mfa.enabled:
        out.append("totp")
    if usable_at_login(db, user):
        out.append("email")
    return out


def locked(row: UserEmailOTP, now: Optional[datetime] = None) -> bool:
    return row.locked_until is not None and row.locked_until > (now or _now())


def issue(db: Session, row: UserEmailOTP) -> str:
    """Replace the current code with a fresh one and return it (the caller mails it). Does not commit."""
    code = generate()
    row.code_hash = _digest(row.user_id, code)
    row.code_expires_at = _now() + timedelta(seconds=CODE_TTL_SECONDS)
    row.attempts = 0
    row.last_sent_at = _now()
    return code


def verify(db: Session, user: User, code: str, *, enrolling: bool = False) -> Optional[bool]:
    """True = correct (spent), False = wrong or none pending, None = just locked out by this attempt.
    Row-locked, so concurrent guesses are counted one after another. Does not commit."""
    row = db.query(UserEmailOTP).filter(UserEmailOTP.user_id == user.id).with_for_update().first()
    if row is None or row.enabled == enrolling or locked(row):
        return False
    if not row.code_hash or row.code_expires_at is None or row.code_expires_at <= _now() or not code or len(code) != 6 or not code.isdigit():
        return False
    if hmac.compare_digest(row.code_hash, _digest(user.id, code)):
        row.code_hash, row.code_expires_at, row.attempts = None, None, 0
        return True
    row.attempts += 1
    if row.attempts >= MAX_ATTEMPTS:
        row.code_hash, row.code_expires_at, row.attempts = None, None, 0
        row.locked_until = _now() + timedelta(minutes=COOLDOWN_MINUTES)
        return None
    return False


def send(user: User, code: str, why: str) -> None:
    """Mail the code to the account's own address. Raises on delivery failure."""
    minutes = CODE_TTL_SECONDS // 60
    body = (f"Your {settings.MFA_ISSUER} verification code is {code}\n\n"
            f"It {why} and expires in {minutes} minutes. Never share it with anyone, including {settings.MFA_ISSUER} staff.\n"
            "If you did not just try to sign in or change your security settings, change your password now.")
    mailer.send(mailer.build(user.email, f"{code} is your {settings.MFA_ISSUER} verification code", body), timeout=10)


def remove(db: Session, user: User) -> None:
    if user.email_otp is not None:
        db.delete(user.email_otp)
