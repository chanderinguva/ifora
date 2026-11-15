"""IFORA-19: per-tenant hosts, issuers, signing keys and background-job context.

Every test that crosses tenants uses two real tenants in the database and the real app; nothing about keys or the
database is mocked. Multi-tenant mode is switched on for the test only (TENANT_RESOLUTION=host).
"""

import base64
import json

import pytest
from fastapi.testclient import TestClient
from lxml import etree

from backend.app import tenancy
from backend.app.api import app
from backend.app.config import settings
from backend.app.db import SessionLocal
from backend.app.oidc import keys
from backend.app.tenancy import (
    Tenant,
    TenantContextMissing,
    TenantDomain,
    TenantNotResolved,
    claim_domain,
    resolve_tenant,
    tenant_session,
    unscoped,
    verify_domain,
)
from tests.test_tenancy import tenant_b  # noqa: F401  (fixture: tenant "acme")

BASE = "idp.test"


@pytest.fixture
def multi(monkeypatch, tenant_b):  # noqa: F811
    """Two tenants: the default one (slug from the database) and 'acme'. Host mode, base domain idp.test."""
    monkeypatch.setattr(settings, "TENANT_RESOLUTION", "host")
    monkeypatch.setattr(settings, "TENANT_BASE_DOMAIN", BASE)
    tenancy.clear_resolution_cache()
    s = SessionLocal()
    with unscoped(s):
        default = s.get(Tenant, tenancy.default_tenant_id())
        default_slug = default.slug
    s.close()
    yield {"a_slug": default_slug, "b_slug": "acme", "a_id": tenancy.default_tenant_id(), "b_id": tenant_b}
    tenancy.clear_resolution_cache()


def client(host):
    return TestClient(app, base_url=f"http://{host}", raise_server_exceptions=False)


def host_of(slug):
    return f"{slug}.{BASE}"


# --- resolution ------------------------------------------------------------------------------------------------------


def test_slug_hosts_resolve_to_their_own_tenant_and_issuer(multi):
    a_id, a_iss = resolve_tenant(host_of(multi["a_slug"]))
    b_id, b_iss = resolve_tenant(host_of("acme"))
    assert (a_id, b_id) == (multi["a_id"], multi["b_id"])
    assert a_iss == f"{settings.OIDC_ISSUER.split('://')[0]}://{multi['a_slug']}.{BASE}"
    assert b_iss.endswith(f"acme.{BASE}") and a_iss != b_iss


def test_unknown_host_is_404_before_any_route_runs_and_nothing_falls_back_to_a_default(multi):
    for path in ("/.well-known/openid-configuration", "/oauth/jwks", "/saml/metadata", "/api/v1/me"):
        r = client("nobody.idp.test").get(path)
        assert r.status_code == 404, path
        assert r.json() == {"detail": "Not found"}
    assert client("localhost").get("/oauth/jwks").status_code == 404  # not under the base domain either
    with pytest.raises(TenantNotResolved):
        resolve_tenant("a.b." + BASE)  # nested labels do not name a tenant


def test_forwarded_host_headers_are_ignored(multi):
    r = client("nobody.idp.test").get("/oauth/jwks", headers={"X-Forwarded-Host": host_of("acme"), "Forwarded": f"host={host_of('acme')}"})
    assert r.status_code == 404


def test_health_is_reachable_with_any_host(multi):
    assert client("probe.internal").get("/health").status_code == 200


def test_a_suspended_tenant_does_not_resolve(multi):
    s = SessionLocal()
    with unscoped(s):
        s.get(Tenant, multi["b_id"]).status = "suspended"
        s.commit()
    s.close()
    tenancy.clear_resolution_cache()
    with pytest.raises(TenantNotResolved):
        resolve_tenant(host_of("acme"))


# --- domains need verification ---------------------------------------------------------------------------------------


def test_a_claimed_domain_resolves_only_after_verification_with_the_right_proof(multi):
    s = SessionLocal()
    try:
        row = claim_domain(s, multi["b_id"], "Login.Example.COM.")
        s.commit()
        assert row.domain == "login.example.com" and row.verified_at is None
        with pytest.raises(TenantNotResolved):
            resolve_tenant("login.example.com")  # claimed, not proven
        assert verify_domain(s, "login.example.com", "wrong-proof") is False
        s.commit()
        with pytest.raises(TenantNotResolved):
            resolve_tenant("login.example.com")
        assert verify_domain(s, "login.example.com", row.verification_token) is True
        s.commit()
    finally:
        s.close()
    tid, iss = resolve_tenant("login.example.com")
    assert tid == multi["b_id"]
    assert iss.endswith(f"acme.{BASE}")  # the issuer comes from the tenant record, not from the host that was asked for


def test_a_domain_cannot_be_claimed_twice_or_stolen_by_another_tenant(multi):
    s = SessionLocal()
    try:
        claim_domain(s, multi["b_id"], "shared.example.com")
        s.commit()
        with pytest.raises(ValueError):
            claim_domain(s, multi["a_id"], "shared.example.com")
        for bad in ("", "nodots", "a/b.example.com", "a b.example.com", "host:8080.example.com"):
            with pytest.raises(ValueError):
                claim_domain(s, multi["a_id"], bad)
    finally:
        s.close()


def test_verification_is_single_use(multi):
    s = SessionLocal()
    try:
        row = claim_domain(s, multi["b_id"], "once.example.com")
        s.commit()
        token = row.verification_token
        assert verify_domain(s, "once.example.com", token) is True
        assert verify_domain(s, "once.example.com", token) is False
    finally:
        s.close()


# --- issuers, discovery, keys ----------------------------------------------------------------------------------------


def test_discovery_names_each_tenants_own_issuer(multi):
    a = client(host_of(multi["a_slug"])).get("/.well-known/openid-configuration").json()
    b = client(host_of("acme")).get("/.well-known/openid-configuration").json()
    assert a["issuer"] != b["issuer"]
    assert a["issuer"].endswith(host_of(multi["a_slug"])) and b["issuer"].endswith(host_of("acme"))
    assert a["jwks_uri"].startswith(a["issuer"]) and b["jwks_uri"].startswith(b["issuer"])


def test_each_tenants_jwks_holds_only_its_own_keys(multi):
    ja = client(host_of(multi["a_slug"])).get("/oauth/jwks").json()["keys"]
    jb = client(host_of("acme")).get("/oauth/jwks").json()["keys"]
    kids_a, kids_b = {k["kid"] for k in ja}, {k["kid"] for k in jb}
    assert kids_a and kids_b and not (kids_a & kids_b)
    for k in ja + jb:
        assert not ({"d", "p", "q", "dp", "dq", "qi"} & set(k))  # public material only


def _token_from(tenant_id, issuer_host):
    """A real access-token-shaped JWT signed with that tenant's active key and its issuer."""
    s = tenant_session(tenant_id)
    try:
        iss = resolve_tenant(issuer_host)[1]
        now = int(__import__("time").time())
        tok = keys.sign_jwt(s, {"iss": iss, "sub": "u", "aud": iss, "client_id": "c", "scope": "openid", "iat": now, "exp": now + 600, "jti": "j"}, typ="at+jwt")
        s.commit()
        return tok, iss
    finally:
        s.close()


def test_a_token_minted_by_tenant_a_is_rejected_by_tenant_b(multi):
    tok_a, iss_a = _token_from(multi["a_id"], host_of(multi["a_slug"]))
    sb = tenant_session(multi["b_id"])
    try:
        iss_b = resolve_tenant(host_of("acme"))[1]
        with pytest.raises(keys.TokenError):  # B's keys do not contain A's kid
            keys.verify_jwt(sb, tok_a, issuer=iss_b, audience=iss_b, typ="at+jwt")
        sa = tenant_session(multi["a_id"])
        try:
            assert keys.verify_jwt(sa, tok_a, issuer=iss_a, audience=iss_a, typ="at+jwt")["iss"] == iss_a  # control
            with pytest.raises(keys.TokenError):  # right keys, wrong issuer: tenant A's token presented under B's issuer
                keys.verify_jwt(sa, tok_a, issuer=iss_b, audience=iss_b, typ="at+jwt")
        finally:
            sa.close()
    finally:
        sb.close()


def test_userinfo_and_introspection_refuse_another_tenants_token(multi):
    tok_a, _ = _token_from(multi["a_id"], host_of(multi["a_slug"]))
    r = client(host_of("acme")).get("/oauth/userinfo", headers={"Authorization": f"Bearer {tok_a}"})
    assert r.status_code == 401
    r = client(host_of(multi["a_slug"])).get("/oauth/userinfo", headers={"Authorization": f"Bearer {tok_a}"})
    assert r.status_code in (401, 403) and r.status_code != 404  # reaches the handler; refused for lack of a real user/client, not for the key


# --- SAML ------------------------------------------------------------------------------------------------------------


def test_saml_metadata_differs_per_tenant(multi):
    ns = {"md": "urn:oasis:names:tc:SAML:2.0:metadata", "ds": "http://www.w3.org/2000/09/xmldsig#"}
    docs = {}
    for slug in (multi["a_slug"], "acme"):
        r = client(host_of(slug)).get("/saml/metadata")
        assert r.status_code == 200, slug
        docs[slug] = etree.fromstring(r.content)
    a, b = docs[multi["a_slug"]], docs["acme"]
    assert a.get("entityID") != b.get("entityID")
    assert a.get("entityID").startswith(resolve_tenant(host_of(multi["a_slug"]))[1])
    certs = [d.find(".//ds:X509Certificate", ns).text.strip() for d in (a, b)]
    assert certs[0] != certs[1]
    locs = [d.find(".//md:SingleSignOnService", ns).get("Location") for d in (a, b)]
    assert locs[0] != locs[1] and locs[0].startswith(resolve_tenant(host_of(multi["a_slug"]))[1])


def test_single_tenant_mode_is_unchanged(db):
    assert settings.TENANT_RESOLUTION == "single"
    assert tenancy.issuer() == settings.OIDC_ISSUER
    assert resolve_tenant("anything.example") == (tenancy.default_tenant_id(), settings.OIDC_ISSUER)


# --- fail closed without a bound issuer ------------------------------------------------------------------------------


def test_issuer_without_a_bound_request_fails_closed_in_multi_tenant_mode(multi):
    with pytest.raises(TenantContextMissing):
        tenancy.issuer()


def test_the_issuer_binding_does_not_leak_between_requests(multi):
    a, b = client(host_of(multi["a_slug"])), client(host_of("acme"))
    first = a.get("/.well-known/openid-configuration").json()["issuer"]
    second = b.get("/.well-known/openid-configuration").json()["issuer"]
    again = a.get("/.well-known/openid-configuration").json()["issuer"]
    assert first == again and first != second
    with pytest.raises(TenantContextMissing):
        tenancy.issuer()  # nothing stays bound after the requests finish
