"""IdP signing certificate lifecycle. Self-signed RSA-2048 (SHA-256); SPs pin the certificate from our metadata.

Three statuses: `active` signs, `next` is staged (published in metadata, not yet signing) and `retired` no longer signs
but is still published until it expires or the operator purges it. The safe rotation is `stage` (SPs import the new
certificate from metadata), wait, then `promote`. `rotate` does both at once for an emergency. Certificates last
SAML_CERT_VALIDITY_DAYS (default 730). Private keys are encrypted with the "saml" purpose key (`keywrap`).
"""

import datetime as dt
from typing import List, Optional, Tuple

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from sqlalchemy.orm import Session

from backend.app import keywrap
from backend.app.config import settings
from backend.app.saml.models import SamlSigningKey


class NoStagedKey(Exception):
    """promote() was called with no staged certificate."""


def _generate(db: Session, status: str = "active") -> SamlSigningKey:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "IdentityForge SAML signing")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(minutes=5))
            .not_valid_after(now + dt.timedelta(days=settings.SAML_CERT_VALIDITY_DAYS)).sign(key, hashes.SHA256()))
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    row = SamlSigningKey(private_key_enc=keywrap.wrap("saml", pem), cert_pem=cert.public_bytes(serialization.Encoding.PEM).decode(),
                         not_after=cert.not_valid_after_utc, status=status)
    db.add(row)
    db.flush()
    return row


def active(db: Session) -> SamlSigningKey:
    row = db.query(SamlSigningKey).filter(SamlSigningKey.status == "active").order_by(SamlSigningKey.id.desc()).first()
    return row or _generate(db)


def rotate(db: Session) -> SamlSigningKey:
    """Immediate rotation: retire the active key and sign with a fresh one now (SPs must already trust it or re-import)."""
    for k in db.query(SamlSigningKey).filter(SamlSigningKey.status == "active").all():
        k.status = "retired"
    return _generate(db)


def staged(db: Session) -> Optional[SamlSigningKey]:
    return db.query(SamlSigningKey).filter(SamlSigningKey.status == "next").order_by(SamlSigningKey.id.desc()).first()


def stage(db: Session) -> SamlSigningKey:
    """Create the next certificate and publish it in metadata without signing with it. Replaces an earlier staged one."""
    db.query(SamlSigningKey).filter(SamlSigningKey.status == "next").delete()
    active(db)  # there is always an active key before a next one exists
    return _generate(db, "next")


def promote(db: Session) -> SamlSigningKey:
    """Make the staged certificate the signing one; the previous active one is retired but stays published."""
    nxt = staged(db)
    if nxt is None:
        raise NoStagedKey("no staged certificate to promote")
    for k in db.query(SamlSigningKey).filter(SamlSigningKey.status == "active").all():
        k.status = "retired"
    nxt.status = "active"
    db.flush()
    return nxt


def purge_retired(db: Session) -> int:
    return db.query(SamlSigningKey).filter(SamlSigningKey.status == "retired").delete()


def private_and_cert(row: SamlSigningKey) -> Tuple[bytes, bytes]:
    return keywrap.unwrap("saml", row.private_key_enc), row.cert_pem.encode()


def published_certs(db: Session) -> List[str]:
    """Base64 DER bodies of every certificate SPs may still pin: active first, then staged, then retired ones that have not expired."""
    now = dt.datetime.now(dt.timezone.utc)
    order = {"active": 0, "next": 1, "retired": 2}
    rows = sorted(db.query(SamlSigningKey).all(), key=lambda r: (order.get(r.status, 3), -r.id))
    rows = [r for r in rows if r.status != "retired" or r.not_after > now]
    if not any(r.status == "active" for r in rows):
        rows.insert(0, active(db))
    return ["".join(r.cert_pem.strip().splitlines()[1:-1]) for r in rows]


def fingerprint(cert_pem: str) -> str:
    c = x509.load_pem_x509_certificate(cert_pem.encode())
    return c.fingerprint(hashes.SHA256()).hex(":").upper()


def days_to_expiry(row: SamlSigningKey, now: Optional[dt.datetime] = None) -> int:
    now = now or dt.datetime.now(dt.timezone.utc)
    return (row.not_after - now).days  # negative once expired


def describe(db: Session) -> List[dict]:
    """What the admin API shows: status, fingerprint and time left for every certificate (never key material)."""
    active(db)
    rows = sorted(db.query(SamlSigningKey).all(), key=lambda r: ({"active": 0, "next": 1, "retired": 2}.get(r.status, 3), -r.id))
    return [{"id": r.id, "status": r.status, "fingerprint_sha256": fingerprint(r.cert_pem), "not_after": r.not_after.isoformat(),
             "days_to_expiry": days_to_expiry(r), "expiring_soon": r.status != "retired" and days_to_expiry(r) <= settings.SAML_CERT_WARN_DAYS}
            for r in rows]
