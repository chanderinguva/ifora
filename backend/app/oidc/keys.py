"""Signing key lifecycle, JWKS and JWT sign/verify (ADR 005 §6).

Lifecycle:  pending --(activate_at)--> active --(newer key activates)--> retired --(retire_at)--> expired
            emergency rotation: pending/active --> revoked (immediately out of JWKS, key wiped)

Overlap rule: a retired key stays in JWKS for  max token TTL + clock skew + JWKS cache TTL,  so every
token it signed can still be verified by relying parties with a stale JWKS cache. A new key is published
(pending) for  JWKS cache TTL + skew  before it starts signing, so caches already know it.
Private keys are Fernet-encrypted with OIDC_KEY_ENCRYPTION_KEY (separate from the MFA key).
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet, RSAKey
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.oidc.models import KeyStatus, SigningKey

SUPPORTED_ALGS = ("RS256",)  # ES256 plugs in by adding an entry to _GENERATORS; verification allow-lists per call
MIN_RSA_BITS = 2048


class KeyConfigError(RuntimeError):
    """OIDC signing is not configured safely (missing/shared encryption key)."""


class TokenError(Exception):
    """A token failed validation. The message is safe to log, not to return to clients verbatim."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def overlap_seconds() -> int:
    ttl = max(settings.OIDC_ID_TOKEN_TTL_SECONDS, settings.OIDC_ACCESS_TOKEN_TTL_SECONDS)
    return ttl + settings.OIDC_CLOCK_SKEW_SECONDS + settings.OIDC_JWKS_CACHE_SECONDS


def publish_delay_seconds() -> int:
    return settings.OIDC_JWKS_CACHE_SECONDS + settings.OIDC_CLOCK_SKEW_SECONDS


def _fernet() -> Fernet:
    key = settings.OIDC_KEY_ENCRYPTION_KEY
    if not key:
        raise KeyConfigError("OIDC_KEY_ENCRYPTION_KEY is not set")
    if key == settings.MFA_ENCRYPTION_KEY:
        raise KeyConfigError("OIDC_KEY_ENCRYPTION_KEY must differ from MFA_ENCRYPTION_KEY")
    try:
        return Fernet(key.encode())
    except ValueError as e:
        raise KeyConfigError("OIDC_KEY_ENCRYPTION_KEY is not a valid Fernet key") from e


def _generate_rs256():
    bits = settings.OIDC_RSA_KEY_BITS
    if bits < MIN_RSA_BITS:
        raise KeyConfigError(f"OIDC_RSA_KEY_BITS must be at least {MIN_RSA_BITS}")
    return RSAKey.generate_key(bits)


_GENERATORS = {"RS256": _generate_rs256}


def _new_key_row(alg: str, status: str, activate_at: datetime) -> SigningKey:
    if alg not in _GENERATORS:
        raise KeyConfigError(f"unsupported signing algorithm {alg!r}")
    fernet = _fernet()
    key = _GENERATORS[alg]()
    kid = key.thumbprint()
    pem = key.as_pem(private=True)
    public = key.as_dict(private=False)
    public.update({"kid": kid, "use": "sig", "alg": alg})
    return SigningKey(
        kid=kid,
        alg=alg,
        status=status,
        private_pem_encrypted=fernet.encrypt(pem).decode(),
        public_jwk=public,
        activate_at=activate_at,
    )


def _wipe(row: SigningKey, status: str) -> None:
    row.status = status
    row.private_pem_encrypted = None


def advance(db: Session, now: Optional[datetime] = None) -> None:
    """Apply time-based transitions (idempotent; takes row locks so concurrent workers agree)."""
    now = now or _now()
    rows = db.query(SigningKey).filter(
        SigningKey.status.in_([KeyStatus.PENDING, KeyStatus.ACTIVE, KeyStatus.RETIRED])
    ).with_for_update().all()
    changed = False
    due = sorted((r for r in rows if r.status == KeyStatus.PENDING and r.activate_at <= now), key=lambda r: r.activate_at)
    if due:
        newest = due[-1]
        for r in rows:
            if r.status == KeyStatus.ACTIVE:
                r.status = KeyStatus.RETIRED
                r.retire_at = now + timedelta(seconds=overlap_seconds())
        db.flush()  # free the single-active slot before activating (partial unique index)
        newest.status = KeyStatus.ACTIVE
        for r in due[:-1]:  # skipped pendings never signed anything
            _wipe(r, KeyStatus.EXPIRED)
        changed = True
    for r in rows:
        if r.status == KeyStatus.RETIRED and r.retire_at is not None and r.retire_at <= now:
            _wipe(r, KeyStatus.EXPIRED)
            changed = True
    if changed:
        db.commit()
    else:
        db.rollback()  # release row locks


def _bootstrap(db: Session, audit=None) -> None:
    """First use: create the initial signing key. The partial unique index makes a concurrent race safe."""
    try:
        db.add(_new_key_row("RS256", KeyStatus.ACTIVE, _now()))
        if audit:
            audit("OIDC_KEY_CREATED")
        db.commit()
    except IntegrityError:
        db.rollback()


def _active(db: Session) -> Optional[SigningKey]:
    return db.query(SigningKey).filter(SigningKey.status == KeyStatus.ACTIVE).first()


def signing_key(db: Session) -> SigningKey:
    advance(db)
    key = _active(db)
    if key is None:
        _bootstrap(db)
        key = _active(db)
    if key is None:
        raise KeyConfigError("no active signing key")
    return key


def rotate(db: Session, *, emergency: bool = False, alg: str = "RS256", audit=None) -> SigningKey:
    """Create the next key. Normal: published now, signs after the publish delay. Emergency: signs
    immediately and every earlier key is revoked (tokens it signed stop verifying)."""
    advance(db)
    rows = db.query(SigningKey).filter(
        SigningKey.status.in_([KeyStatus.PENDING, KeyStatus.ACTIVE, KeyStatus.RETIRED])
    ).with_for_update().all()
    now = _now()
    if emergency:
        for r in rows:
            _wipe(r, KeyStatus.REVOKED)
        db.flush()
        new = _new_key_row(alg, KeyStatus.ACTIVE, now)
    else:
        if any(r.status == KeyStatus.PENDING for r in rows):
            db.rollback()
            raise KeyConfigError("a rotation is already in progress")
        has_active = any(r.status == KeyStatus.ACTIVE for r in rows)
        new = _new_key_row(
            alg,
            KeyStatus.PENDING if has_active else KeyStatus.ACTIVE,
            now + timedelta(seconds=publish_delay_seconds()) if has_active else now,
        )
    db.add(new)
    if audit:
        audit("OIDC_KEY_ROTATED", {"kid": new.kid, "alg": new.alg, "emergency": emergency, "status": new.status})
    db.commit()
    return new


def public_jwks(db: Session) -> dict:
    """Public keys only: active + pending (pre-published) + retired (still inside the overlap)."""
    advance(db)
    if _active(db) is None:
        _bootstrap(db)
    rows = (
        db.query(SigningKey)
        .filter(SigningKey.status.in_([KeyStatus.ACTIVE, KeyStatus.PENDING, KeyStatus.RETIRED]))
        .order_by(SigningKey.created_at)
        .all()
    )
    return {"keys": [r.public_jwk for r in rows]}


def sign_jwt(db: Session, claims: dict, *, typ: str = "JWT") -> str:
    row = signing_key(db)
    key = RSAKey.import_key(
        _decrypt(row), parameters={"kid": row.kid, "use": "sig", "alg": row.alg}
    )
    header = {"alg": row.alg, "kid": row.kid, "typ": typ}
    return jwt.encode(header, claims, key, algorithms=[row.alg])


def _decrypt(row: SigningKey) -> bytes:
    if not row.private_pem_encrypted:
        raise KeyConfigError("signing key material is not available")
    try:
        return _fernet().decrypt(row.private_pem_encrypted.encode())
    except InvalidToken as e:
        raise KeyConfigError("cannot decrypt signing key (wrong OIDC_KEY_ENCRYPTION_KEY?)") from e


def verify_jwt(
    db: Session,
    token: str,
    *,
    issuer: str,
    audience: str,
    typ: Optional[str] = None,
    algorithms: tuple = ("RS256",),
) -> dict:
    """Validate signature (algorithm allow-list, key chosen by kid from our own JWKS), issuer, audience,
    expiry and, when given, the `typ` header. Never trusts the token's `alg`. Returns the claims."""
    from joserfc.jwt import JWTClaimsRegistry

    jwks = public_jwks(db)
    # only keys that have actually been signing may verify; a pending key has signed nothing
    pending = {
        r.kid for r in db.query(SigningKey.kid).filter(SigningKey.status == KeyStatus.PENDING)
    }
    keyset = KeySet.import_key_set({"keys": [k for k in jwks["keys"] if k["kid"] not in pending]})
    try:
        decoded = jwt.decode(token, keyset, algorithms=list(algorithms))
        if typ is not None and decoded.header.get("typ") != typ:
            raise TokenError("unexpected token type")
        JWTClaimsRegistry(
            leeway=settings.OIDC_CLOCK_SKEW_SECONDS,
            iss={"essential": True, "value": issuer},
            aud={"essential": True, "value": audience},
            exp={"essential": True},
        ).validate(decoded.claims)
    except TokenError:
        raise
    except (JoseError, ValueError, KeyError) as e:
        raise TokenError(f"invalid token: {type(e).__name__}") from e
    return decoded.claims
