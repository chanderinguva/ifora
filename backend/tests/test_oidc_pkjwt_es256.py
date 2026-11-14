"""M8: ES256 signing keys and private_key_jwt client authentication."""

import base64
import time
import uuid
from datetime import timedelta

import pytest
import redis
from joserfc import jwt
from joserfc.jwk import ECKey, RSAKey

from backend.app import ratelimit
from backend.app.config import settings
from backend.app.oidc import client_auth, keys
from backend.app.oidc.models import SigningKey
from tests.test_oidc_token import CB, VERIFIER, exchange, get_code, mk as mk_user_client, post_token, user_api  # noqa: F401 (fixture)
from tests.test_oidc_service_clients import mk_service

TOKEN_URL = f"{settings.OIDC_ISSUER.rstrip('/')}/oauth/token"


def pub(key, kid, **extra):
    d = key.as_dict(private=False)
    d.update({"kid": kid, **extra})
    return d


@pytest.fixture(scope="module")
def ec():
    return ECKey.generate_key("P-256")


@pytest.fixture(scope="module")
def ec2():
    return ECKey.generate_key("P-256")


@pytest.fixture(scope="module")
def rsa():
    return RSAKey.generate_key(2048)


def assertion(client, key, kid="k1", alg="ES256", aud=TOKEN_URL, **over):
    t = int(time.time())
    claims = {"iss": client["client_id"], "sub": client["client_id"], "aud": aud, "iat": t, "exp": t + 60, "jti": str(uuid.uuid4())}
    claims.update(over)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode({"alg": alg, "kid": kid}, claims, key, algorithms=[alg])


def form(a, **extra):
    return {"client_assertion_type": client_auth.ASSERTION_TYPE, "client_assertion": a, **extra}


def mk_pk(super_admin, key, kid="k1", **kw):
    return mk_user_client(super_admin, client_type="confidential", token_endpoint_auth_method="private_key_jwt",
                          jwks={"keys": [pub(key, kid)]}, **kw)


def code_exchange(api, client, a, **extra):
    data = {"grant_type": "authorization_code", "code": get_code(api, client), "redirect_uri": CB, "code_verifier": VERIFIER, **form(a), **extra}
    return post_token(api, data)


# ---- ES256 signing keys ---------------------------------------------------------------------------------

def test_es256_keys_sign_and_verify_and_coexist_with_rs256(db, super_admin, user_api):
    c = mk_user_client(super_admin, client_type="confidential")
    old = exchange(user_api, c, get_code(user_api, c)).json()["access_token"]          # signed by the RS256 key
    assert jwt.decode(old, keys.KeySet.import_key_set(keys.public_jwks(db)), algorithms=["RS256"]).header["alg"] == "RS256"

    new = keys.rotate(db, alg="ES256")                                                 # published now, signs after the delay
    assert new.alg == "ES256" and new.status == "pending"
    new.activate_at = new.activate_at - timedelta(days=1)
    db.commit()
    keys.advance(db)

    t = exchange(user_api, c, get_code(user_api, c)).json()
    h = jwt.decode(t["access_token"], keys.KeySet.import_key_set(keys.public_jwks(db)), algorithms=["ES256"]).header
    assert h["alg"] == "ES256" and h["kid"] == new.kid
    algs = {k["alg"] for k in keys.public_jwks(db)["keys"]}
    assert algs == {"RS256", "ES256"}                                                  # overlap: both published
    for tok in (old, t["access_token"], t["id_token"]):                                # and both verify
        assert keys.verify_jwt(db, tok, issuer=settings.OIDC_ISSUER, audience=settings.OIDC_ISSUER if tok != t["id_token"] else c["client_id"])
    row = db.query(SigningKey).filter(SigningKey.kid == new.kid).one()
    assert "PRIVATE" not in str(row.public_jwk) and row.public_jwk["kty"] == "EC" and "d" not in row.public_jwk


def test_default_algorithm_comes_from_settings(db, monkeypatch):
    monkeypatch.setattr(settings, "OIDC_SIGNING_ALG", "ES256")
    assert keys.signing_key(db).alg == "ES256"                                         # first key ever created


def test_unknown_algorithm_is_refused(db, super_admin):
    with pytest.raises(keys.KeyConfigError):
        keys.rotate(db, alg="HS256")
    assert super_admin.post("/admin/oidc/keys/rotate", {"alg": "HS256"}).status_code == 422
    assert super_admin.post("/admin/oidc/keys/rotate", {"alg": "ES256"}).status_code == 201


def test_discovery_advertises_the_published_algorithms(db, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.app.main import app
    monkeypatch.setattr(settings, "OIDC_SIGNING_ALG", "ES256")
    d = TestClient(app).get("/.well-known/openid-configuration").json()
    assert d["id_token_signing_alg_values_supported"] == ["ES256"]
    assert "private_key_jwt" in d["token_endpoint_auth_methods_supported"]
    assert d["token_endpoint_auth_signing_alg_values_supported"] == ["RS256", "ES256"]


def test_hs256_forged_with_the_public_key_is_rejected(db):
    jwk = keys.public_jwks(db)["keys"][0]
    forged = jwt.encode({"alg": "HS256", "kid": jwk["kid"], "typ": "at+jwt"},
                        {"iss": settings.OIDC_ISSUER, "aud": settings.OIDC_ISSUER, "exp": int(time.time()) + 60},
                        __import__("joserfc.jwk", fromlist=["OctKey"]).OctKey.import_key(b"x" * 32), algorithms=["HS256"])
    with pytest.raises(keys.TokenError):
        keys.verify_jwt(db, forged, issuer=settings.OIDC_ISSUER, audience=settings.OIDC_ISSUER)


# ---- registering private_key_jwt clients ----------------------------------------------------------------

def test_registration_has_no_secret(super_admin, ec):
    r = super_admin.post("/admin/oidc/clients", {"name": "pk", "client_type": "confidential", "redirect_uris": [CB],
                                                 "token_endpoint_auth_method": "private_key_jwt", "jwks": {"keys": [pub(ec, "k1")]}})
    assert r.status_code == 201, r.text
    b = r.json()
    assert "client_secret" not in b and b["secrets"] == [] and b["token_endpoint_auth_method"] == "private_key_jwt"
    assert b["jwks"]["keys"][0]["kid"] == "k1"
    assert super_admin.post(f"/admin/oidc/clients/{b['id']}/secrets", {}).status_code == 409


def bad_jwks(over):
    return {"keys": [over]}


@pytest.mark.parametrize("make,msg", [
    (lambda ec, rsa: {"keys": [{**pub(ec, "k1"), "d": "AAAA"}]}, "public keys only"),
    (lambda ec, rsa: {"keys": [{k: v for k, v in pub(ec, "k1").items() if k != "kid"}]}, "kid"),
    (lambda ec, rsa: {"keys": [pub(ec, "k1"), pub(ec, "k1")]}, "duplicate kid"),
    (lambda ec, rsa: {"keys": [pub(ec, f"k{i}") for i in range(6)]}, "at most"),
    (lambda ec, rsa: {"keys": [{**pub(ec, "k1"), "use": "enc"}]}, "use=sig"),
    (lambda ec, rsa: {"keys": [{**pub(ec, "k1"), "crv": "P-384"}]}, "P-256"),
    (lambda ec, rsa: {"keys": [{**pub(rsa, "k1"), "alg": "RS512"}]}, "RS256"),
    (lambda ec, rsa: {"keys": [{"kty": "oct", "kid": "k", "k": "AAAA"}]}, "public keys only"),
    (lambda ec, rsa: {"keys": []}, "non-empty"),
    (lambda ec, rsa: {"nothing": 1}, "non-empty"),
])
def test_jwks_validation(super_admin, ec, rsa, make, msg):
    r = super_admin.post("/admin/oidc/clients", {"name": "pk", "client_type": "confidential", "redirect_uris": [CB],
                                                 "token_endpoint_auth_method": "private_key_jwt", "jwks": make(ec, rsa)})
    assert r.status_code == 422 and msg in r.json()["detail"], r.text


def test_weak_rsa_is_refused(super_admin):
    weak = RSAKey.generate_key(1024)
    r = super_admin.post("/admin/oidc/clients", {"name": "pk", "client_type": "confidential", "redirect_uris": [CB],
                                                 "token_endpoint_auth_method": "private_key_jwt", "jwks": {"keys": [pub(weak, "k1")]}})
    assert r.status_code == 422 and "2048" in r.json()["detail"]


def test_method_and_jwks_must_agree(super_admin, ec):
    base = {"name": "x", "redirect_uris": [CB]}
    j = {"keys": [pub(ec, "k1")]}
    for extra in ({"client_type": "confidential", "token_endpoint_auth_method": "private_key_jwt"},       # no jwks
                  {"client_type": "confidential", "jwks": j},                                              # jwks without the method
                  {"client_type": "public", "jwks": j},
                  {"client_type": "public", "token_endpoint_auth_method": "private_key_jwt", "jwks": j},
                  {"client_type": "confidential", "token_endpoint_auth_method": "client_secret_post"}):
        assert super_admin.post("/admin/oidc/clients", {**base, **extra}).status_code == 422, extra


# ---- authenticating with an assertion -------------------------------------------------------------------

def test_authorization_code_exchange_with_an_es256_assertion(super_admin, user_api, ec):
    c = mk_pk(super_admin, ec)
    r = code_exchange(user_api, c, assertion(c, ec))
    assert r.status_code == 200 and r.json()["id_token"], r.text


def test_rs256_assertion_and_issuer_as_audience(super_admin, user_api, rsa):
    c = mk_pk(super_admin, rsa)
    r = code_exchange(user_api, c, assertion(c, rsa, alg="RS256", aud=settings.OIDC_ISSUER))
    assert r.status_code == 200, r.text


def test_service_client_with_private_key_jwt(super_admin, user_api, ec):
    c = mk_service(super_admin, token_endpoint_auth_method="private_key_jwt", jwks={"keys": [pub(ec, "k1")]})
    assert "client_secret" not in c
    r = post_token(user_api, {"grant_type": "client_credentials", **form(assertion(c, ec))})
    assert r.status_code == 200 and r.json()["scope"] == "invoices:read invoices:write"


def fails(r):
    return r.status_code == 401 and r.json()["error"] == "invalid_client"


def test_bad_assertions_are_all_invalid_client(super_admin, user_api, ec, ec2):
    c = mk_pk(super_admin, ec)
    other = mk_pk(super_admin, ec2)
    now = int(time.time())
    cases = {
        "signed by another key": assertion(c, ec2),
        "unknown kid": assertion(c, ec, kid="nope"),
        "expired": assertion(c, ec, iat=now - 600, exp=now - 300),
        "wrong audience": assertion(c, ec, aud="https://evil.example.com/oauth/token"),
        "iss is another client": assertion(c, ec, iss=other["client_id"]),
        "sub is another client": assertion(c, ec, sub=other["client_id"]),
        "no jti": assertion(c, ec, jti=None),
        "no exp": assertion(c, ec, exp=None),
        "lifetime too long": assertion(c, ec, exp=now + 3600),
        "not yet valid": assertion(c, ec, nbf=now + 3600),
    }
    for name, a in cases.items():
        r = post_token(user_api, {"grant_type": "authorization_code", "code": "x", "redirect_uri": CB, "code_verifier": VERIFIER, **form(a)})
        assert fails(r), (name, r.text)


def test_algorithm_confusion_is_refused(super_admin, user_api, ec):
    from joserfc.jwk import OctKey
    c = mk_pk(super_admin, ec)
    t = int(time.time())
    hs = jwt.encode({"alg": "HS256", "kid": "k1"}, {"iss": c["client_id"], "sub": c["client_id"], "aud": TOKEN_URL, "exp": t + 60, "jti": "j"},
                    OctKey.import_key(b"y" * 32), algorithms=["HS256"])
    none = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode() + "." + base64.urlsafe_b64encode(
        ('{"iss":"%s","sub":"%s","aud":"%s","exp":%d,"jti":"j"}' % (c["client_id"], c["client_id"], TOKEN_URL, t + 60)).encode()).rstrip(b"=").decode() + "."
    for a in (hs, none):
        assert fails(post_token(user_api, {"grant_type": "client_credentials", **form(a)}))


def test_an_assertion_is_single_use(super_admin, user_api, ec):
    c = mk_service(super_admin, token_endpoint_auth_method="private_key_jwt", jwks={"keys": [pub(ec, "k1")]})
    a = assertion(c, ec)
    assert post_token(user_api, {"grant_type": "client_credentials", **form(a)}).status_code == 200
    assert fails(post_token(user_api, {"grant_type": "client_credentials", **form(a)}))             # replay
    assert post_token(user_api, {"grant_type": "client_credentials", **form(assertion(c, ec))}).status_code == 200  # a fresh one is fine


def test_replay_store_failure_fails_closed(super_admin, user_api, ec, monkeypatch):
    c = mk_service(super_admin, token_endpoint_auth_method="private_key_jwt", jwks={"keys": [pub(ec, "k1")]})

    def boom():
        raise redis.RedisError("down")
    monkeypatch.setattr(ratelimit, "_redis", boom)
    assert fails(post_token(user_api, {"grant_type": "client_credentials", **form(assertion(c, ec))}))


def test_wrong_method_for_the_client(super_admin, user_api, ec):
    secret_client = mk_service(super_admin)
    assert fails(post_token(user_api, {"grant_type": "client_credentials", **form(assertion(secret_client, ec))}))
    pk = mk_service(super_admin, token_endpoint_auth_method="private_key_jwt", jwks={"keys": [pub(ec, "k1")]})
    from tests.test_oidc_service_clients import basic
    assert post_token(user_api, {"grant_type": "client_credentials"}, basic(pk, "idf_cs_anything")).status_code == 401  # no secret path


def test_mixing_methods_and_malformed_requests(super_admin, user_api, ec):
    c = mk_service(super_admin, token_endpoint_auth_method="private_key_jwt", jwks={"keys": [pub(ec, "k1")]})
    from tests.test_oidc_service_clients import basic
    r = post_token(user_api, {"grant_type": "client_credentials", **form(assertion(c, ec))}, basic(c, "idf_cs_x"))
    assert r.status_code == 400 and r.json()["error"] == "invalid_request"
    assert fails(post_token(user_api, {"grant_type": "client_credentials", "client_assertion": assertion(c, ec)}))     # no type
    assert fails(post_token(user_api, {"grant_type": "client_credentials", "client_assertion_type": "urn:wrong", "client_assertion": assertion(c, ec)}))
    assert fails(post_token(user_api, {"grant_type": "client_credentials", **form(assertion(c, ec), client_id="someone-else")}))
    assert fails(post_token(user_api, {"grant_type": "client_credentials", **form("x" * 5000)}))


def test_disabled_client_and_key_rotation(super_admin, user_api, ec, ec2):
    c = mk_service(super_admin, token_endpoint_auth_method="private_key_jwt", jwks={"keys": [pub(ec, "k1")]})
    both = super_admin.patch(f"/admin/oidc/clients/{c['id']}", {"jwks": {"keys": [pub(ec, "k1"), pub(ec2, "k2")]}})
    assert both.status_code == 200
    assert post_token(user_api, {"grant_type": "client_credentials", **form(assertion(c, ec2, kid="k2"))}).status_code == 200
    super_admin.patch(f"/admin/oidc/clients/{c['id']}", {"jwks": {"keys": [pub(ec2, "k2")]}})        # old key retired
    assert fails(post_token(user_api, {"grant_type": "client_credentials", **form(assertion(c, ec))}))
    assert super_admin.patch(f"/admin/oidc/clients/{c['id']}", {"jwks": {"keys": [{**pub(ec2, "k2"), "d": "x"}]}}).status_code == 422
    super_admin.patch(f"/admin/oidc/clients/{c['id']}", {"status": "disabled"})
    assert fails(post_token(user_api, {"grant_type": "client_credentials", **form(assertion(c, ec2, kid="k2"))}))


def test_jwks_update_only_for_private_key_clients(super_admin, ec):
    c = mk_service(super_admin)
    assert super_admin.patch(f"/admin/oidc/clients/{c['id']}", {"jwks": {"keys": [pub(ec, "k1")]}}).status_code == 422


def test_introspection_and_revocation_accept_assertions(super_admin, user_api, ec):
    c = mk_service(super_admin, token_endpoint_auth_method="private_key_jwt", jwks={"keys": [pub(ec, "k1")]})
    t = post_token(user_api, {"grant_type": "client_credentials", **form(assertion(c, ec))}).json()["access_token"]
    url = f"{settings.OIDC_ISSUER.rstrip('/')}/oauth/introspect"
    r = user_api.c.post("/oauth/introspect", data={"token": t, **form(assertion(c, ec, aud=url))})
    assert r.status_code == 200 and r.json()["active"] is True
    r = user_api.c.post("/oauth/revoke", data={"token": "idf_rt_nope", **form(assertion(c, ec, aud=f"{settings.OIDC_ISSUER.rstrip('/')}/oauth/revoke"))})
    assert r.status_code == 200
