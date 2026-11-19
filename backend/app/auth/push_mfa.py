"""Push sign-in approval with number matching (IFORA-77).

How it works: after the password, the login screen shows a two-digit number. Every enrolled browser of the person is woken with an
empty Web Push (VAPID-signed, RFC 8030/8292, so no payload crosses the push service). The browser asks Ifora for the pending request
using its own device secret and is offered three numbers; picking the one on the login screen approves. The login screen then
exchanges the approval for a session at `/login/mfa` (`factor: "push"`), which is the only place a session is created.

Rules: a challenge lives 90 seconds, can be answered once, and dies with its login challenge. One wrong pick or a deny ends it; wrong
picks count toward the account lockout and three in 15 minutes block new requests. Only the browser vendors' push services are ever
contacted. The number and the decision are never logged.
"""

import base64
import hashlib
import hmac
import random
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlsplit

import httpx
import structlog
from sqlalchemy.orm import Session

from backend.app.auth.mfa_model import MFAChallenge, PushChallenge, PushDevice
from backend.app.config import settings
from backend.app.security_policy import service as sec_policy
from backend.app.users.model import User

logger = structlog.get_logger(__name__)

CHALLENGE_TTL_SECONDS = 90
START_LIMIT = 3  # login-screen requests per START_WINDOW_SECONDS, per user and per IP
START_WINDOW_SECONDS = 60
FAIL_LIMIT = 3  # wrong picks per FAIL_WINDOW_SECONDS before new requests are refused
FAIL_WINDOW_SECONDS = 900
MAX_DEVICES = 5
VAPID_TTL_HOURS = 12

# Tests (and only tests) replace delivery: overrides["send"](endpoint) -> "ok" | "gone" | "failed"; overrides["transport"] -> httpx transport.
overrides: Dict[str, Any] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _h(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


# ---- VAPID ------------------------------------------------------------------------------------------------------

def configured() -> bool:
    return bool(settings.VAPID_PRIVATE_KEY and settings.VAPID_SUBJECT)


def _private_key():
    from cryptography.hazmat.primitives.asymmetric import ec

    raw = base64.urlsafe_b64decode(settings.VAPID_PRIVATE_KEY + "=" * (-len(settings.VAPID_PRIVATE_KEY) % 4))
    return ec.derive_private_key(int.from_bytes(raw, "big"), ec.SECP256R1())


def public_key() -> str:
    """The application server key a browser subscribes with (uncompressed P-256 point, base64url)."""
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    return _b64(_private_key().public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint))


def _authorization(endpoint: str) -> str:
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
    from joserfc import jwt
    from joserfc.jwk import ECKey

    u = urlsplit(endpoint)
    claims = {"aud": f"{u.scheme}://{u.netloc}", "exp": int(time.time()) + VAPID_TTL_HOURS * 3600, "sub": settings.VAPID_SUBJECT}
    pem = _private_key().private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    token = jwt.encode({"alg": "ES256", "typ": "JWT"}, claims, ECKey.import_key(pem))
    return f"vapid t={token}, k={public_key()}"


def valid_endpoint(endpoint: str) -> bool:
    """Only https URLs on a known push service's host, default port: the server must never be made to call arbitrary URLs."""
    if not endpoint or len(endpoint) > 2048:
        return False
    try:
        u = urlsplit(endpoint)
        host, port = (u.hostname or "").lower(), u.port
    except ValueError:
        return False
    if u.scheme != "https" or u.username or u.password or (port not in (None, 443)):
        return False
    return any(host == s or host.endswith("." + s) for s in settings.PUSH_ALLOWED_HOST_SUFFIXES)


def send(endpoint: str) -> str:
    """Wake a device with an empty push. Returns "ok", "gone" (the subscription no longer exists) or "failed"."""
    if "send" in overrides:
        return overrides["send"](endpoint)
    try:
        with httpx.Client(timeout=10, follow_redirects=False, transport=overrides.get("transport")) as c:
            r = c.post(endpoint, headers={"Authorization": _authorization(endpoint), "TTL": str(CHALLENGE_TTL_SECONDS), "Urgency": "high", "Content-Length": "0"})
    except Exception as e:  # noqa: BLE001 - the endpoint is a per-device URL and never goes to the log
        logger.warning("push.send_failed", error=type(e).__name__)
        return "failed"
    if r.status_code in (200, 201, 202):
        return "ok"
    if r.status_code in (404, 410):
        return "gone"
    logger.warning("push.send_rejected", status=r.status_code)
    return "failed"


# ---- policy -----------------------------------------------------------------------------------------------------

def audience_policy(db: Session, user: User) -> str:
    p = sec_policy.get(db)
    return p.push_admins if user.is_admin else p.push_members


def allowed(db: Session, user: User) -> bool:
    return audience_policy(db, user) in ("allowed", "required")


def required_for(db: Session, user: User) -> bool:
    return bool(user.is_admin and audience_policy(db, user) == "required")


def required_but_missing(db: Session, user: User) -> bool:
    """Administrators only: the policy mandates a device and this admin has none. Never enforced when push cannot be delivered."""
    return bool(required_for(db, user) and configured() and not user.push_devices)


def usable_at_login(db: Session, user: User) -> bool:
    return bool(user.push_devices) and allowed(db, user) and configured()


# ---- devices ----------------------------------------------------------------------------------------------------

def enrol(db: Session, user: User, name: str, endpoint: str) -> tuple:
    """Create a device and return (device, secret). The secret is shown to the browser once; only its hash is kept. Does not commit."""
    secret = secrets.token_urlsafe(32)
    device = PushDevice(user_id=user.id, name=name.strip()[:80] or "Browser", endpoint=endpoint, endpoint_hash=_h(endpoint), secret_hash=_h(secret))
    db.add(device)
    db.flush()
    return device, secret


def device_for(db: Session, header: Optional[str]) -> Optional[PushDevice]:
    """`Authorization: Device <id>.<secret>` -> the device, comparing the secret in constant time."""
    if not header or not header.startswith("Device ") or len(header) > 120:
        return None
    ident, _, secret = header[7:].partition(".")
    if not ident.isdigit() or not secret:
        return None
    device = db.get(PushDevice, int(ident))
    if device is None or not hmac.compare_digest(device.secret_hash, _h(secret)):
        return None
    return device


# ---- challenges -------------------------------------------------------------------------------------------------

def locked(user: User) -> bool:
    from backend.app import ratelimit

    return ratelimit.is_limited("push_fail_user", str(user.id), FAIL_LIMIT)


def _choices() -> tuple:
    rng = random.SystemRandom()
    pool = list(range(10, 100))
    rng.shuffle(pool)
    picks = [f"{n:02d}" for n in pool[:3]]
    number = picks[0]
    rng.shuffle(picks)
    return number, picks


def start(db: Session, user: User, ch: MFAChallenge, ip: str) -> PushChallenge:
    """Create (replacing any earlier) the approval request for this login. Does not commit."""
    db.query(PushChallenge).filter(PushChallenge.mfa_challenge_id == ch.id).delete(synchronize_session=False)
    number, picks = _choices()
    row = PushChallenge(user_id=user.id, mfa_challenge_id=ch.id, number=number, choices=picks, requested_ip=ip,
                        expires_at=_now() + timedelta(seconds=CHALLENGE_TTL_SECONDS))
    db.add(row)
    db.flush()
    return row


def notify_devices(db: Session, user: User) -> int:
    """Wake every device; forget the ones the push service says are gone. Returns how many accepted the push. Does not commit."""
    delivered = 0
    for d in list(user.push_devices):
        result = send(d.endpoint)
        if result == "ok":
            delivered += 1
        elif result == "gone":
            db.delete(d)
    return delivered


def pending_for(db: Session, user: User) -> Optional[PushChallenge]:
    return (db.query(PushChallenge).filter(PushChallenge.user_id == user.id, PushChallenge.status == "pending", PushChallenge.expires_at > _now())
            .order_by(PushChallenge.id.desc()).first())


def for_login(db: Session, ch: MFAChallenge) -> Optional[PushChallenge]:
    return db.query(PushChallenge).filter(PushChallenge.mfa_challenge_id == ch.id).first()


def state_of(row: Optional[PushChallenge]) -> str:
    if row is None:
        return "none"
    if row.status == "pending" and row.expires_at <= _now():
        return "expired"
    return row.status


def consume_approved(db: Session, ch: MFAChallenge) -> bool:
    """True once, if this login's request was approved in time (it is deleted so it cannot be used twice). Does not commit."""
    row = db.query(PushChallenge).filter(PushChallenge.mfa_challenge_id == ch.id).with_for_update().first()  # two simultaneous exchanges cannot both win
    if state_of(row) != "approved":
        return False
    db.delete(row)
    return True


def view(row: PushChallenge) -> Dict[str, Any]:
    return {"challenge_id": row.id, "choices": list(row.choices), "expires_in": max(0, int((row.expires_at - _now()).total_seconds())),
            "requested_from": row.requested_ip, "requested_at": row.created_at.isoformat() if row.created_at else None}


def new_vapid_key() -> List[str]:
    """[private (base64url scalar), public] for the VAPID_PRIVATE_KEY setting."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    k = ec.generate_private_key(ec.SECP256R1())
    return [_b64(k.private_numbers().private_value.to_bytes(32, "big")),
            _b64(k.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint))]


if __name__ == "__main__":
    priv, pub = new_vapid_key()
    print(f"VAPID_PRIVATE_KEY={priv}\nVAPID_SUBJECT=mailto:you@example.com\n# public (the browser fetches it from the API): {pub}")
