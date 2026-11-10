"""OIDC client registry: what a client may be, secret handling, client authentication, isolation."""

from datetime import datetime, timedelta, timezone

import pytest

from backend.app.oidc import clients as svc
from backend.app.oidc.models import OIDCClient, OIDCClientSecret

BASE = {"name": "Demo app", "redirect_uris": ["https://demo.example.com/callback"]}


def mk(api, **kw):
    r = api.post("/admin/oidc/clients", {**BASE, **kw})
    assert r.status_code == 201, r.text
    return r.json()


# ---- access ----------------------------------------------------------------------------

def test_admin_only(member, admin):
    assert member.get("/admin/oidc/clients").status_code == 403
    assert member.post("/admin/oidc/clients", BASE).status_code == 403
    assert admin.get("/admin/oidc/clients").status_code == 200


def test_first_party_flag_is_super_admin_only(admin, super_admin):
    r = admin.post("/admin/oidc/clients", {**BASE, "first_party": True})
    assert r.status_code == 403
    c = mk(super_admin, first_party=True)
    assert c["first_party"] is True
    plain = mk(admin, name="Other")
    assert admin.patch(f"/admin/oidc/clients/{plain['id']}", {"first_party": True}).status_code == 403
    assert admin.patch(f"/admin/oidc/clients/{c['id']}", {"name": "Renamed"}).status_code == 200  # other edits fine


# ---- redirect URI rules (RFC 9700) ------------------------------------------------------

@pytest.mark.parametrize("uri", [
    "http://demo.example.com/cb",               # http off loopback
    "https://*.example.com/cb",                 # wildcard
    "https://demo.example.com/cb#frag",         # fragment
    "https://user:pw@demo.example.com/cb",      # credentials
    "demo.example.com/cb",                      # not absolute
    "javascript:alert(1)", "myapp://callback", "ftp://example.com/cb", "",
    "https://demo.example.com/cb ",             # surrounding space
    "https://demo.example.com/" + "a" * 2000,   # absurd length
])
def test_bad_redirect_uris_rejected(admin, uri):
    assert admin.post("/admin/oidc/clients", {**BASE, "redirect_uris": [uri]}).status_code == 422


@pytest.mark.parametrize("uri", [
    "https://demo.example.com/callback", "https://demo.example.com:8443/cb?x=1",
    "http://localhost:3000/cb", "http://127.0.0.1:8080/cb", "http://[::1]:9000/cb",
])
def test_good_redirect_uris_accepted(admin, uri):
    assert mk(admin, redirect_uris=[uri])["redirect_uris"] == [uri]


def test_redirect_uri_list_rules(admin):
    assert admin.post("/admin/oidc/clients", {**BASE, "redirect_uris": []}).status_code == 422
    same = "https://a.example.com/cb"
    assert admin.post("/admin/oidc/clients", {**BASE, "redirect_uris": [same, same]}).status_code == 422
    many = [f"https://a.example.com/cb{i}" for i in range(11)]
    assert admin.post("/admin/oidc/clients", {**BASE, "redirect_uris": many}).status_code == 422
    assert admin.post("/admin/oidc/clients", {**BASE, "post_logout_redirect_uris": ["http://evil.example.com/"]}).status_code == 422
    assert mk(admin, post_logout_redirect_uris=["https://demo.example.com/bye"])["post_logout_redirect_uris"]


# ---- scopes and grants ------------------------------------------------------------------

def test_scope_rules(admin):
    assert admin.post("/admin/oidc/clients", {**BASE, "allowed_scopes": ["profile"]}).status_code == 422       # no openid
    assert admin.post("/admin/oidc/clients", {**BASE, "allowed_scopes": ["openid", "admin"]}).status_code == 422
    c = mk(admin, allowed_scopes=["email", "openid", "openid"])
    assert c["allowed_scopes"] == ["openid", "email"] and c["grant_types"] == ["authorization_code"]
    c2 = mk(admin, name="With refresh", allowed_scopes=["openid", "offline_access"])
    assert c2["grant_types"] == ["authorization_code", "refresh_token"]


def test_only_safe_grants_are_ever_offered(admin):
    c = mk(admin, allowed_scopes=list(svc.SUPPORTED_SCOPES))
    assert not ({"implicit", "password", "client_credentials"} & set(c["grant_types"]))


# ---- client types and secrets --------------------------------------------------------------

def test_public_client_has_no_secret(admin):
    c = mk(admin)
    assert c["client_type"] == "public" and c["token_endpoint_auth_method"] == "none"
    assert "client_secret" not in c and c["secrets"] == []
    assert admin.post(f"/admin/oidc/clients/{c['id']}/secrets", {}).status_code == 409


def test_confidential_secret_is_shown_once_and_stored_hashed(db, admin):
    c = mk(admin, client_type="confidential")
    secret = c["client_secret"]
    assert secret.startswith("idf_cs_") and len(secret) > 40
    again = admin.get(f"/admin/oidc/clients/{c['id']}").text
    assert secret not in again and "secret_hash" not in again
    row = db.query(OIDCClientSecret).one()
    assert secret not in row.secret_hash and row.secret_hash.startswith("$argon2") and row.hint == secret[-4:]


def test_secret_rotation_allows_two_active_and_revocation(db, admin):
    c = mk(admin, client_type="confidential")
    first = c["client_secret"]
    r = admin.post(f"/admin/oidc/clients/{c['id']}/secrets", {"expires_in_days": 30})
    assert r.status_code == 201
    second = r.json()["client_secret"]
    assert admin.post(f"/admin/oidc/clients/{c['id']}/secrets", {}).status_code == 409   # max two
    assert svc.authenticate_client(db, c["client_id"], first) and svc.authenticate_client(db, c["client_id"], second)
    old_id = c["secrets"][0]["id"]
    assert admin.delete(f"/admin/oidc/clients/{c['id']}/secrets/{old_id}").status_code == 200
    db.expire_all()
    assert svc.authenticate_client(db, c["client_id"], first) is None
    assert svc.authenticate_client(db, c["client_id"], second) is not None


# ---- client authentication ---------------------------------------------------------------

def test_authenticate_client(db, admin):
    c = mk(admin, client_type="confidential")
    good, cid = c["client_secret"], c["client_id"]
    assert svc.authenticate_client(db, cid, good).client_id == cid
    assert db.query(OIDCClientSecret).one().last_used_at is not None
    assert svc.authenticate_client(db, cid, good + "x") is None
    assert svc.authenticate_client(db, cid, "") is None
    assert svc.authenticate_client(db, cid, None) is None
    assert svc.authenticate_client(db, "idf_unknown", good) is None


def test_expired_disabled_and_public_clients_cannot_authenticate(db, admin):
    c = mk(admin, client_type="confidential")
    good, cid = c["client_secret"], c["client_id"]
    row = db.query(OIDCClientSecret).one()
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    assert svc.authenticate_client(db, cid, good) is None
    row.expires_at = None
    db.commit()
    assert svc.authenticate_client(db, cid, good) is not None
    assert admin.patch(f"/admin/oidc/clients/{c['id']}", {"status": "disabled"}).status_code == 200
    db.expire_all()
    assert svc.authenticate_client(db, cid, good) is None
    pub = mk(admin, name="Pub")
    assert svc.authenticate_client(db, pub["client_id"], "anything") is None


# ---- lifecycle, audit, isolation -----------------------------------------------------------

def test_update_validates_and_delete_cascades(db, admin):
    c = mk(admin, client_type="confidential")
    assert admin.patch(f"/admin/oidc/clients/{c['id']}", {"redirect_uris": ["http://evil.example.com/"]}).status_code == 422
    r = admin.patch(f"/admin/oidc/clients/{c['id']}", {"redirect_uris": ["https://new.example.com/cb"], "allowed_scopes": ["openid", "offline_access"]})
    assert r.status_code == 200 and r.json()["grant_types"] == ["authorization_code", "refresh_token"]
    assert admin.delete(f"/admin/oidc/clients/{c['id']}").status_code == 200
    assert db.query(OIDCClient).count() == 0 and db.query(OIDCClientSecret).count() == 0
    assert admin.get(f"/admin/oidc/clients/{c['id']}").status_code == 404


def test_audit_never_contains_secrets(admin):
    c = mk(admin, client_type="confidential")
    admin.post(f"/admin/oidc/clients/{c['id']}/secrets", {})
    admin.patch(f"/admin/oidc/clients/{c['id']}", {"status": "disabled"})
    body = admin.get("/admin/audit?count=100").text
    for a in ("OIDC_CLIENT_CREATED", "OIDC_CLIENT_SECRET_ROTATED", "OIDC_CLIENT_UPDATED"):
        assert a in body
    assert c["client_secret"] not in body and "idf_cs_" not in body


def test_clients_are_tenant_scoped(db, admin):
    from backend.app.db import SessionLocal, engine
    from backend.app.tenancy import Tenant, unscoped, use_tenant

    mk(admin)
    s = SessionLocal()
    with unscoped(s):
        t = Tenant(slug="acme-clients", name="Acme")
        s.add(t)
        s.commit()
        tid = t.id
    try:
        other = use_tenant(SessionLocal(), tid)
        try:
            assert other.query(OIDCClient).count() == 0
            assert svc.authenticate_client(other, db.query(OIDCClient).one().client_id, "x") is None
        finally:
            other.close()
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql("DELETE FROM tenants WHERE id = %s", (tid,))
        s.close()
