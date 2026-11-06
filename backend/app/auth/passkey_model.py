"""WebAuthn persistence: registered passkeys and single-use ceremony challenges."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, LargeBinary, String
from sqlalchemy.orm import backref, relationship

from backend.app.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Passkey(Base):
    __tablename__ = "passkeys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    credential_id = Column(String(1024), nullable=False, unique=True)  # base64url
    public_key = Column(LargeBinary, nullable=False)  # COSE key
    sign_count = Column(Integer, nullable=False, default=0)
    name = Column(String(100), nullable=False)
    transports = Column(String(100), nullable=True)  # comma separated, hint for the browser
    device_type = Column(String(32), nullable=False, default="single_device")  # or multi_device (synced)
    backed_up = Column(Boolean, nullable=False, default=False)
    aaguid = Column(String(36), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship(
        "User", backref=backref("passkeys", cascade="all, delete-orphan", order_by="Passkey.id")
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "device_type": self.device_type,
            "backed_up": self.backed_up,
            "transports": self.transports.split(",") if self.transports else [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
        }


class WebAuthnChallenge(Base):
    """A pending ceremony. Single use: consumed (deleted) on the first verify attempt."""

    __tablename__ = "webauthn_challenges"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ceremony_hash = Column(String(64), nullable=False, unique=True)
    purpose = Column(String(20), nullable=False)  # "register" | "login"
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    challenge = Column(LargeBinary, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
