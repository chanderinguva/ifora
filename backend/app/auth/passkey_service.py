"""WebAuthn ceremonies (py_webauthn does the cryptographic verification)."""

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.orm import Session
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from backend.app.auth.passkey_model import Passkey, WebAuthnChallenge
from backend.app.config import settings
from backend.app.users.model import User


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _h(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


# ---- ceremony (challenge) storage ------------------------------------------------

def _store(db: Session, purpose: str, challenge: bytes, user: Optional[User]) -> str:
    db.query(WebAuthnChallenge).filter(WebAuthnChallenge.expires_at < _now()).delete(synchronize_session=False)
    raw = secrets.token_urlsafe(32)
    db.add(
        WebAuthnChallenge(
            ceremony_hash=_h(raw),
            purpose=purpose,
            user_id=user.id if user else None,
            challenge=challenge,
            expires_at=_now() + timedelta(seconds=settings.WEBAUTHN_CEREMONY_SECONDS),
        )
    )
    db.commit()
    return raw


def consume(db: Session, ceremony_id: str, purpose: str, user_id: Optional[int] = None) -> Optional[bytes]:
    """Return the challenge and delete the row (single use, even if verification later fails)."""
    if not ceremony_id or len(ceremony_id) > 128:
        return None
    row = db.query(WebAuthnChallenge).filter(WebAuthnChallenge.ceremony_hash == _h(ceremony_id)).first()
    if row is None:
        return None
    challenge, ok = row.challenge, True
    if row.expires_at < _now() or row.purpose != purpose or (user_id is not None and row.user_id != user_id):
        ok = False
    db.delete(row)
    db.commit()
    return challenge if ok else None


# ---- registration -----------------------------------------------------------------

def ensure_handle(db: Session, user: User) -> bytes:
    if not user.webauthn_handle:
        user.webauthn_handle = bytes_to_base64url(secrets.token_bytes(32))
        db.flush()
    return base64url_to_bytes(user.webauthn_handle)


def registration_options(db: Session, user: User) -> Tuple[str, Dict[str, Any]]:
    handle = ensure_handle(db, user)
    options = generate_registration_options(
        rp_id=settings.WEBAUTHN_RP_ID,
        rp_name=settings.WEBAUTHN_RP_NAME,
        user_id=handle,
        user_name=user.email,
        user_display_name=f"{user.first_name} {user.last_name}".strip() or user.email,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,  # discoverable: enables usernameless sign-in
            user_verification=UserVerificationRequirement.REQUIRED,  # biometric / PIN, so the passkey is MFA by itself
        ),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(p.credential_id)) for p in user.passkeys
        ],
    )
    ceremony = _store(db, "register", options.challenge, user)
    return ceremony, json.loads(options_to_json(options))


def verify_registration(db: Session, user: User, challenge: bytes, credential: Dict[str, Any], name: str) -> Passkey:
    """Raises on any verification failure."""
    v = verify_registration_response(
        credential=credential,
        expected_challenge=challenge,
        expected_rp_id=settings.WEBAUTHN_RP_ID,
        expected_origin=settings.WEBAUTHN_ORIGINS,
        require_user_verification=True,
    )
    cred_id = bytes_to_base64url(v.credential_id)
    if db.query(Passkey.id).filter(Passkey.credential_id == cred_id).first():
        raise ValueError("credential already registered")
    transports = (credential.get("response") or {}).get("transports") or []
    passkey = Passkey(
        user_id=user.id,
        credential_id=cred_id,
        public_key=v.credential_public_key,
        sign_count=v.sign_count,
        name=name,
        transports=",".join(t for t in transports if isinstance(t, str))[:100] or None,
        device_type=getattr(v.credential_device_type, "value", str(v.credential_device_type)),
        backed_up=bool(v.credential_backed_up),
        aaguid=str(v.aaguid) if v.aaguid else None,
    )
    db.add(passkey)
    return passkey


# ---- authentication ---------------------------------------------------------------

def authentication_options(db: Session) -> Tuple[str, Dict[str, Any]]:
    """Usernameless: no allowCredentials, so the authenticator offers its discoverable passkeys."""
    options = generate_authentication_options(
        rp_id=settings.WEBAUTHN_RP_ID,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    ceremony = _store(db, "login", options.challenge, None)
    return ceremony, json.loads(options_to_json(options))


class AuthFailure(Exception):
    def __init__(self, reason: str, user: Optional[User] = None):
        super().__init__(reason)
        self.reason, self.user = reason, user


def verify_authentication(db: Session, challenge: bytes, credential: Dict[str, Any]) -> Tuple[User, Passkey]:
    """Verify an assertion; updates the signature counter. Raises AuthFailure."""
    cred_id = credential.get("id")
    if not isinstance(cred_id, str):
        raise AuthFailure("malformed")
    passkey = db.query(Passkey).filter(Passkey.credential_id == cred_id).first()
    if passkey is None:
        raise AuthFailure("unknown_credential")
    user = db.get(User, passkey.user_id)
    if user is None:
        raise AuthFailure("unknown_credential")

    handle = (credential.get("response") or {}).get("userHandle")
    if handle and handle != user.webauthn_handle:
        raise AuthFailure("handle_mismatch", user)

    try:
        v = verify_authentication_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=settings.WEBAUTHN_RP_ID,
            expected_origin=settings.WEBAUTHN_ORIGINS,
            credential_public_key=passkey.public_key,
            credential_current_sign_count=passkey.sign_count,
            require_user_verification=True,
        )
    except Exception as e:  # noqa: BLE001 - library raises several specific types; all mean "reject"
        reason = "counter_rollback" if "sign count" in str(e).lower() else "invalid_assertion"
        raise AuthFailure(reason, user) from e

    passkey.sign_count = v.new_sign_count
    passkey.backed_up = bool(v.credential_backed_up)
    passkey.last_used_at = _now()
    return user, passkey
