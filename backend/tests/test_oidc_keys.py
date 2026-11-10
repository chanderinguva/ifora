"""Signing keys: JWKS, encryption at rest, rotation overlap, emergency revocation, token validation."""

import base64
import json
import time
from datetime import timedelta

import pytest
from cryptography.fernet import Fernet
from joserfc import jwt
from joserfc.jwk import OctKey

from backend.app.config import settings
from backend.app.oidc import keys
from backend.app.oidc.models import KeyStatus, SigningKey
from tests.conftest import Api

ISS = settings.OIDC_ISSUER
AUD = "api://orders"


def claims(**kw):
    now = int(time.time())
    return {"iss": ISS, "aud": AUD, "sub": "u1", "iat": now, "exp": now + 300, **kw}


def sign(db, **kw):
    return keys.sign_jwt(db, claims(**kw), typ="at+jwt")


def verify(db, token, **kw):
    return keys.verify_jwt(db, token, issuer=ISS, audience=AUD, typ="at+jwt", **kw)


def jwks_kids(db):
    return [k["kid"] for k in keys.public_jwks(db)["keys"]]


def b64json(part):
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


# ---- bootstrap, JWKS, storage ----------------------------------------------------

def test_first_use_creates_one_active_key_and_jwks_has_public_material_only(db):
    body = keys.public_jwks(db)
    assert len(body["keys"]) == 1
    jwk = body["keys"][0]
    assert jwk["kty"] == "RSA" and jwk["alg"] == "RS256" and jwk["use"] == "sig" and jwk["kid"]
    assert not ({"d", "p", "q", "dp", "dq", "qi"} & set(jwk))
    assert db.query(SigningKey).filter_by(status=KeyStatus.ACTIVE).count() == 1


def test_private_key_is_encrypted_at_rest(db):
    keys.public_jwks(db)
    row = db.query(SigningKey).one()
    assert "PRIVATE KEY" not in row.private_pem_encrypted
    assert b"PRIVATE KEY" in Fernet(settings.OIDC_KEY_ENCRYPTION_KEY.encode()).decrypt(row.private_pem_encrypted.encode())


def test_jwks_endpoint_is_public_cacheable_and_leaks_no_private_material():
    r = Api().c.get("/oauth/jwks")
    assert r.status_code == 200
    assert r.headers["cache-control"].startswith("public, max-age=")
    assert r.headers["access-control-allow-origin"] == "*"
    assert "set-cookie" not in r.headers
    assert not ({"d", "p", "q"} & set(r.json()["keys"][0]))


def test_encryption_key_must_be_configured_and_distinct(db, monkeypatch):
    monkeypatch.setattr(settings, "OIDC_KEY_ENCRYPTION_KEY", "")
    with pytest.raises(keys.KeyConfigError):
        keys.public_jwks(db)
    monkeypatch.setattr(settings, "OIDC_KEY_ENCRYPTION_KEY", settings.MFA_ENCRYPTION_KEY)
    with pytest.raises(keys.KeyConfigError):
        keys.public_jwks(db)
    assert Api().c.get("/oauth/jwks").status_code == 503


def test_weak_rsa_size_refused(db, monkeypatch):
    monkeypatch.setattr(settings, "OIDC_RSA_KEY_BITS", 1024)
    with pytest.raises(keys.KeyConfigError):
        keys.public_jwks(db)


# ---- token signing and validation -------------------------------------------------

def test_signed_token_has_kid_alg_typ_and_validates(db):
    tok = sign(db)
    header = b64json(tok.split(".")[0])
    assert header["alg"] == "RS256" and header["typ"] == "at+jwt" and header["kid"] in jwks_kids(db)
    assert verify(db, tok)["sub"] == "u1"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda: dict(iss="https://evil.example"),
        lambda: dict(aud="api://other"),
        lambda: dict(exp=int(time.time()) - 3600),
    ],
)
def test_wrong_issuer_audience_or_expired_rejected(db, mutate):
    with pytest.raises(keys.TokenError):
        verify(db, sign(db, **mutate()))


def test_missing_required_claims_rejected(db):
    c = claims()
    del c["aud"]
    with pytest.raises(keys.TokenError):
        verify(db, keys.sign_jwt(db, c, typ="at+jwt"))


def test_wrong_typ_rejected(db):
    tok = keys.sign_jwt(db, claims(), typ="JWT")
    with pytest.raises(keys.TokenError):
        verify(db, tok)


def test_tampered_payload_rejected(db):
    h, p, s = sign(db).split(".")
    forged = b64json(p)
    forged["sub"] = "admin"
    p2 = base64.urlsafe_b64encode(json.dumps(forged).encode()).rstrip(b"=").decode()
    with pytest.raises(keys.TokenError):
        verify(db, f"{h}.{p2}.{s}")


def test_alg_none_and_hs256_confusion_rejected(db):
    kid = jwks_kids(db)[0]
    none = (
        base64.urlsafe_b64encode(json.dumps({"alg": "none", "kid": kid, "typ": "at+jwt"}).encode()).rstrip(b"=").decode()
        + "."
        + base64.urlsafe_b64encode(json.dumps(claims()).encode()).rstrip(b"=").decode()
        + "."
    )
    with pytest.raises(keys.TokenError):
        verify(db, none)
    # HS256 "signed" with the public modulus as the HMAC secret (classic algorithm-confusion attack)
    n = keys.public_jwks(db)["keys"][0]["n"]
    hs = jwt.encode({"alg": "HS256", "kid": kid, "typ": "at+jwt"}, claims(), OctKey.import_key(n), algorithms=["HS256"])
    with pytest.raises(keys.TokenError):
        verify(db, hs)


def test_token_signed_by_unknown_key_rejected(db):
    from joserfc.jwk import RSAKey

    rogue = RSAKey.generate_key(2048)
    tok = jwt.encode({"alg": "RS256", "kid": jwks_kids(db)[0], "typ": "at+jwt"}, claims(), rogue)
    with pytest.raises(keys.TokenError):
        verify(db, tok)


# ---- rotation -----------------------------------------------------------------------

def _age(db, seconds):
    """Move every key's timestamps into the past (time travel without sleeping)."""
    for r in db.query(SigningKey).all():
        r.activate_at -= timedelta(seconds=seconds)
        if r.retire_at:
            r.retire_at -= timedelta(seconds=seconds)
    db.commit()


def test_rotation_publishes_new_key_before_it_signs(db):
    old = keys.signing_key(db).kid
    new = keys.rotate(db)
    assert new.status == KeyStatus.PENDING
    assert set(jwks_kids(db)) == {old, new.kid}          # published early so caches learn it
    assert keys.signing_key(db).kid == old               # but not signing yet
    with pytest.raises(keys.KeyConfigError):             # one rotation at a time
        keys.rotate(db)


def test_rotation_overlap_old_tokens_verify_then_stop(db):
    old_kid = keys.signing_key(db).kid
    old_token = sign(db)
    new = keys.rotate(db)

    _age(db, keys.publish_delay_seconds() + 1)           # new key's publish delay has elapsed
    assert keys.signing_key(db).kid == new.kid
    new_token = sign(db)
    assert b64json(new_token.split(".")[0])["kid"] == new.kid
    assert verify(db, old_token)["sub"] == "u1"          # still valid during the overlap
    assert verify(db, new_token)["sub"] == "u1"
    assert set(jwks_kids(db)) == {old_kid, new.kid}
    retired = db.query(SigningKey).filter_by(kid=old_kid).one()
    assert retired.status == KeyStatus.RETIRED

    _age(db, keys.overlap_seconds() + 1)                 # overlap over
    keys.advance(db)
    db.expire_all()
    assert jwks_kids(db) == [new.kid]
    gone = db.query(SigningKey).filter_by(kid=old_kid).one()
    assert gone.status == KeyStatus.EXPIRED and gone.private_pem_encrypted is None
    with pytest.raises(keys.TokenError):
        verify(db, old_token)
    assert verify(db, new_token)["sub"] == "u1"


def test_overlap_covers_token_lifetime_plus_skew_and_cache():
    assert keys.overlap_seconds() >= settings.OIDC_ACCESS_TOKEN_TTL_SECONDS + settings.OIDC_CLOCK_SKEW_SECONDS + settings.OIDC_JWKS_CACHE_SECONDS


def test_pending_key_cannot_validate_tokens(db):
    from joserfc.jwk import RSAKey  # noqa: F401

    keys.signing_key(db)
    new = keys.rotate(db)
    row = db.query(SigningKey).filter_by(kid=new.kid).one()
    pem = __import__("cryptography.fernet", fromlist=["Fernet"]).Fernet(settings.OIDC_KEY_ENCRYPTION_KEY.encode()).decrypt(row.private_pem_encrypted.encode())
    from joserfc.jwk import RSAKey as K

    k = K.import_key(pem, parameters={"kid": new.kid})
    tok = jwt.encode({"alg": "RS256", "kid": new.kid, "typ": "at+jwt"}, claims(), k)
    with pytest.raises(keys.TokenError):
        verify(db, tok)


def test_emergency_rotation_revokes_old_keys_immediately(db):
    old_kid = keys.signing_key(db).kid
    old_token = sign(db)
    new = keys.rotate(db, emergency=True)
    assert new.status == KeyStatus.ACTIVE and keys.signing_key(db).kid == new.kid
    assert jwks_kids(db) == [new.kid]
    with pytest.raises(keys.TokenError):
        verify(db, old_token)
    old = db.query(SigningKey).filter_by(kid=old_kid).one()
    assert old.status == KeyStatus.REVOKED and old.private_pem_encrypted is None


def test_database_allows_only_one_active_key(db):
    from sqlalchemy.exc import IntegrityError

    keys.signing_key(db)
    dup = keys._new_key_row("RS256", KeyStatus.ACTIVE, keys._now())
    db.add(dup)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# ---- admin API / audit / tenancy -----------------------------------------------------

def test_admin_key_api_requires_super_admin_and_never_returns_key_material(admin, super_admin, member):
    assert member.get("/admin/oidc/keys").status_code == 403
    assert admin.get("/admin/oidc/keys").status_code == 403           # plain admin is not enough
    assert admin.post("/admin/oidc/keys/rotate", {}).status_code == 403
    assert super_admin.get("/admin/oidc/keys").status_code == 200
    r = super_admin.post("/admin/oidc/keys/rotate", {})
    assert r.status_code == 201, r.text
    text = super_admin.get("/admin/oidc/keys").text
    assert "private" not in text.lower() and '"d"' not in text and "PRIVATE" not in text


def test_rotation_is_audited_and_emergency_needs_confirmation(super_admin):
    super_admin.get("/admin/oidc/keys")
    assert super_admin.post("/admin/oidc/keys/rotate", {"emergency": True}).status_code == 400
    assert super_admin.post("/admin/oidc/keys/rotate", {"emergency": True, "confirm": True}).status_code == 201
    r = super_admin.get("/admin/audit?action=OIDC_KEY_ROTATED").json()
    assert r["totalResults"] == 1 and r["Resources"][0]["metadata"]["emergency"] is True
    assert "private" not in json.dumps(r).lower()


def test_keys_are_per_tenant(db):
    from backend.app.db import SessionLocal
    from backend.app.tenancy import Tenant, unscoped, use_tenant

    keys.signing_key(db)
    s = SessionLocal()
    with unscoped(s):
        t = Tenant(slug="acme-keys", name="Acme")
        s.add(t)
        s.commit()
        tid = t.id
    try:
        other = use_tenant(SessionLocal(), tid)
        try:
            assert jwks_kids(other) != jwks_kids(db)   # separate key per tenant
            assert other.query(SigningKey).count() == 1
        finally:
            other.close()
    finally:
        from backend.app.db import engine

        with engine.begin() as conn:
            conn.exec_driver_sql("DELETE FROM oidc_signing_keys WHERE tenant_id = %s", (tid,))
            conn.exec_driver_sql("DELETE FROM tenants WHERE id = %s", (tid,))
        s.close()
