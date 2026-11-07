"""One-time tokens for invitations and password resets. Only a keyed hash is stored; the raw token is emailed once."""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.db import Base
from backend.app.tenancy import TenantOwned
from backend.app.users.model import User

PURPOSES = ("reset", "invite")


def _hash(raw: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), b"password-token:" + raw.encode(), hashlib.sha256).hexdigest()


class PasswordToken(TenantOwned, Base):
    __tablename__ = "password_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    purpose = Column(String(8), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


def issue(db: Session, user: User, purpose: str) -> str:
    """Create a token (replacing the user's earlier unused ones of any purpose). Caller commits."""
    assert purpose in PURPOSES
    now = datetime.now(timezone.utc)
    db.query(PasswordToken).filter(PasswordToken.user_id == user.id, PasswordToken.used_at.is_(None)).update({"used_at": now})
    raw = secrets.token_urlsafe(32)
    ttl = timedelta(hours=settings.INVITE_HOURS) if purpose == "invite" else timedelta(minutes=settings.PASSWORD_RESET_MINUTES)
    db.add(PasswordToken(user_id=user.id, purpose=purpose, token_hash=_hash(raw), expires_at=now + ttl))
    db.flush()
    return raw


def lookup(db: Session, raw: str) -> Optional[PasswordToken]:
    if not raw or len(raw) > 100:
        return None
    t = db.query(PasswordToken).filter(PasswordToken.token_hash == _hash(raw)).first()
    if t is None or t.used_at is not None or t.expires_at <= datetime.now(timezone.utc):
        return None
    return t


def link(raw: str, purpose: str) -> str:
    page = "accept-invite" if purpose == "invite" else "reset-password"
    return f"{settings.PUBLIC_APP_URL.rstrip('/')}/{page}#token={raw}"  # fragment: never sent to servers or logged
