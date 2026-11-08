"""IdP signing certificate lifecycle. Self-signed RSA-2048 (SHA-256); SPs pin the certificate from our metadata.

Rotation retires the active key but keeps publishing its certificate, so SPs that still pin the old one keep
working until they re-import the metadata; `purge_retired` removes retired keys the operator is done with.
"""

import datetime as dt
from typing import List, Tuple

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from sqlalchemy.orm import Session

from backend.app.oidc.keys import _fernet
from backend.app.saml.models import SamlSigningKey


def _generate(db: Session) -> SamlSigningKey:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "IdentityForge SAML signing")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(minutes=5))
            .not_valid_after(now + dt.timedelta(days=3650)).sign(key, hashes.SHA256()))
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    row = SamlSigningKey(private_key_enc=_fernet().encrypt(pem).decode(), cert_pem=cert.public_bytes(serialization.Encoding.PEM).decode(),
                         not_after=cert.not_valid_after_utc, status="active")
    db.add(row)
    db.flush()
    return row


def active(db: Session) -> SamlSigningKey:
    row = db.query(SamlSigningKey).filter(SamlSigningKey.status == "active").order_by(SamlSigningKey.id.desc()).first()
    return row or _generate(db)


def rotate(db: Session) -> SamlSigningKey:
    for k in db.query(SamlSigningKey).filter(SamlSigningKey.status == "active").all():
        k.status = "retired"
    return _generate(db)


def purge_retired(db: Session) -> int:
    return db.query(SamlSigningKey).filter(SamlSigningKey.status == "retired").delete()


def private_and_cert(row: SamlSigningKey) -> Tuple[bytes, bytes]:
    return _fernet().decrypt(row.private_key_enc.encode()), row.cert_pem.encode()


def published_certs(db: Session) -> List[str]:
    """Base64 DER bodies of every certificate SPs may still pin (active first)."""
    rows = db.query(SamlSigningKey).order_by(SamlSigningKey.status, SamlSigningKey.id.desc()).all()
    if not rows:
        rows = [active(db)]
    return ["".join(r.cert_pem.strip().splitlines()[1:-1]) for r in rows]


def fingerprint(cert_pem: str) -> str:
    c = x509.load_pem_x509_certificate(cert_pem.encode())
    return c.fingerprint(hashes.SHA256()).hex(":").upper()
