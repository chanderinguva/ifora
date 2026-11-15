"""IFORA-25: signing keys are encrypted with a key per purpose; legacy rows stay readable; the migration is reversible."""

import pytest
from alembic import command
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import text

from backend.app import keywrap
from backend.app.config import settings
from backend.app.db import engine
from backend.app.oidc import keys as oidc_keys
from backend.app.oidc.models import SigningKey
from backend.app.saml import keys as saml_keys
from backend.app.saml.models import SamlSigningKey
from tests.conftest import alembic_config


def _legacy(plain: bytes) -> str:
    return Fernet(settings.OIDC_KEY_ENCRYPTION_KEY.encode()).encrypt(plain).decode()


def test_values_carry_their_purpose_and_round_trip():
    for purpose in keywrap.PURPOSES:
        v = keywrap.wrap(purpose, b"secret-material")
        assert v.startswith(f"v2:{purpose}:") and "secret-material" not in v
        assert keywrap.unwrap(purpose, v) == b"secret-material"
    assert keywrap.wrap("saml", b"x") != keywrap.wrap("saml", b"x")  # Fernet is randomised


def test_a_saml_key_does_not_decrypt_with_the_oidc_subkey_or_the_oidc_key(db):
    row = saml_keys.active(db)
    db.commit()
    token = row.private_key_enc.split(":", 2)[2]
    assert row.private_key_enc.startswith("v2:saml:")
    with pytest.raises(InvalidToken):
        keywrap.subkey("oidc").decrypt(token.encode())  # AC3: not with the OIDC subkey
    with pytest.raises(InvalidToken):
        Fernet(settings.OIDC_KEY_ENCRYPTION_KEY.encode()).decrypt(token.encode())  # nor with the master secret itself
    assert b"PRIVATE KEY" in keywrap.subkey("saml").decrypt(token.encode())
    with pytest.raises(keywrap.KeyWrapError):
        keywrap.unwrap("oidc", row.private_key_enc)  # a value tagged for SAML is refused for OIDC even before decrypting
    forged = "v2:oidc:" + token  # re-tagging does not help
    with pytest.raises(keywrap.KeyWrapError):
        keywrap.unwrap("oidc", forged)


def test_an_oidc_key_does_not_decrypt_with_the_saml_subkey(db):
    oidc_keys.public_jwks(db)
    row = db.query(SigningKey).filter(SigningKey.status == "active").one()
    assert row.private_pem_encrypted.startswith("v2:oidc:")
    with pytest.raises(InvalidToken):
        keywrap.subkey("saml").decrypt(row.private_pem_encrypted.split(":", 2)[2].encode())


def test_a_dedicated_saml_secret_survives_compromise_of_the_oidc_secret(db, monkeypatch):
    monkeypatch.setattr(settings, "SAML_KEY_ENCRYPTION_KEY", Fernet.generate_key().decode())
    assert keywrap.dedicated_secret("saml")
    row = saml_keys.rotate(db)
    db.commit()
    token = row.private_key_enc.split(":", 2)[2].encode()
    # an attacker holding OIDC_KEY_ENCRYPTION_KEY can derive every OIDC-side key, and none of them opens the SAML key
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    import base64

    master = settings.OIDC_KEY_ENCRYPTION_KEY.encode()
    for info in (b"ifora/key-wrap/v2/oidc", b"ifora/key-wrap/v2/saml"):
        sub = Fernet(base64.urlsafe_b64encode(HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(master)))
        with pytest.raises(InvalidToken):
            sub.decrypt(token)
    assert saml_keys.private_and_cert(row)[0].startswith(b"-----BEGIN PRIVATE KEY")  # the legitimate path still works


def test_the_saml_secret_must_not_equal_the_oidc_or_mfa_secret(monkeypatch):
    monkeypatch.setattr(settings, "SAML_KEY_ENCRYPTION_KEY", settings.OIDC_KEY_ENCRYPTION_KEY)
    with pytest.raises(keywrap.KeyWrapError):
        keywrap.subkey("saml")
    monkeypatch.setattr(settings, "SAML_KEY_ENCRYPTION_KEY", settings.MFA_ENCRYPTION_KEY)
    with pytest.raises(keywrap.KeyWrapError):
        keywrap.subkey("saml")


def test_a_wrong_key_is_a_clean_error_and_never_echoes_the_value(db, monkeypatch):
    row = saml_keys.active(db)
    db.commit()
    monkeypatch.setattr(settings, "OIDC_KEY_ENCRYPTION_KEY", Fernet.generate_key().decode())
    with pytest.raises(keywrap.KeyWrapError) as e:
        saml_keys.private_and_cert(row)
    assert row.private_key_enc not in str(e.value) and "PRIVATE" not in str(e.value)


def test_legacy_rows_are_still_read_and_the_migration_rewraps_them_both_ways(db):
    # a legacy (pre-IFORA-25) SAML row and OIDC row, written the old way
    saml_row = saml_keys.active(db)
    plain_saml = saml_keys.private_and_cert(saml_row)[0]
    saml_row.private_key_enc = _legacy(plain_saml)
    db.commit()  # the OIDC bootstrap below may roll the session back
    oidc_keys.public_jwks(db)
    orow = db.query(SigningKey).filter(SigningKey.status == "active").one()
    plain_oidc = oidc_keys._decrypt(orow)
    orow.private_pem_encrypted = _legacy(plain_oidc)
    db.commit()
    sid, oid = saml_row.id, orow.id
    # dual read: both still work without any migration
    assert saml_keys.private_and_cert(db.query(SamlSigningKey).filter_by(id=sid).one())[0] == plain_saml
    assert oidc_keys._decrypt(db.query(SigningKey).filter_by(id=oid).one()) == plain_oidc
    db.close()

    cfg = alembic_config()
    try:
        command.downgrade(cfg, "0060")  # no-op on legacy rows
        command.upgrade(cfg, "head")  # AC3: after the migration both still decrypt, now purpose-separated
        with engine.connect() as c:
            s_enc = c.execute(text("SELECT private_key_enc FROM saml_signing_keys WHERE id = :i"), {"i": sid}).scalar()
            o_enc = c.execute(text("SELECT private_pem_encrypted FROM oidc_signing_keys WHERE id = :i"), {"i": oid}).scalar()
        assert s_enc.startswith("v2:saml:") and o_enc.startswith("v2:oidc:")
        assert keywrap.unwrap("saml", s_enc) == plain_saml and keywrap.unwrap("oidc", o_enc) == plain_oidc
        with pytest.raises(InvalidToken):
            Fernet(settings.OIDC_KEY_ENCRYPTION_KEY.encode()).decrypt(s_enc.split(":", 2)[2].encode())

        command.upgrade(cfg, "head")  # idempotent
        command.downgrade(cfg, "0060")  # reversible: back to the legacy format
        with engine.connect() as c:
            s_old = c.execute(text("SELECT private_key_enc FROM saml_signing_keys WHERE id = :i"), {"i": sid}).scalar()
            o_old = c.execute(text("SELECT private_pem_encrypted FROM oidc_signing_keys WHERE id = :i"), {"i": oid}).scalar()
        assert not s_old.startswith("v2:") and not o_old.startswith("v2:")
        assert Fernet(settings.OIDC_KEY_ENCRYPTION_KEY.encode()).decrypt(s_old.encode()) == plain_saml
        assert Fernet(settings.OIDC_KEY_ENCRYPTION_KEY.encode()).decrypt(o_old.encode()) == plain_oidc
    finally:
        command.upgrade(cfg, "head")
        from backend.app.tenancy import reset_tenant_cache

        reset_tenant_cache()


def test_the_next_status_migration_downgrades_cleanly(db):
    saml_keys.active(db)
    saml_keys.stage(db)
    db.commit()
    db.close()
    cfg = alembic_config()
    try:
        command.downgrade(cfg, "0059")  # staged keys never signed anything and are dropped; the constraint is restored
        with engine.connect() as c:
            assert c.execute(text("SELECT count(*) FROM saml_signing_keys WHERE status = 'next'")).scalar() == 0
            assert c.execute(text("SELECT count(*) FROM saml_signing_keys WHERE status = 'active'")).scalar() == 1
    finally:
        command.upgrade(cfg, "head")
        from backend.app.tenancy import reset_tenant_cache

        reset_tenant_cache()
