"""/oauth/token, /oauth/userinfo, discovery: code exchange, PKCE, replay, client auth, token contents."""

import base64
import hashlib
from datetime import timedelta
from urllib.parse import parse_qs, quote, urlsplit

import pytest

from backend.app.audit.model import AuditEvent
from backend.app.config import settings
from backend.app.oidc import authorize as az, keys
from backend.app.oidc.models import AuthorizationCode
from tests.conftest import Api, make_user

CB = "https://demo.example.com/callback"
VERIFIER = "v" * 60
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()


@pytest.fixture
def user_api(db):
    u = make_user(db, "alice@example.com", first_name="Alice", last_name="Liddell")
    u.set_profile_attributes({"timezone": "Europe/London", "locale": "en-GB", "department": "R&D"})
    db.commit()
    a = Api()
    assert a.login(u.email).status_code == 200
    a.user = u
    return a


def mk(super_admin, **kw):
    r = super_admin.post("/admin/oidc/clients", {"name": "Demo", "redirect_uris": [CB], "first_party": True,
                                                  "allowed_scopes": ["openid", "profile", "email", "groups"], **kw})
    assert r.status_code == 201, r.text
    return r.json()


def get_code(user_api, client, scope="openid profile email", nonce="nonce-1"):
    p = {"client_id": client["client_id"], "redirect_uri": CB, "response_type": "code", "scope": scope, "state": "s",
         "nonce": nonce, "code_challenge": CHALLENGE, "code_challenge_method": "S256"}
    r = user_api.c.get("/oauth/authorize", params=p, follow_redirects=False)
    assert r.status_code == 303, r.text
    return parse_qs(urlsplit(r.headers["location"]).query)["code"][0]


def basic(client):
    cred = f"{quote(client['client_id'], safe='')}:{quote(client['client_secret'], safe='')}"
    return {"Authorization": "Basic " + base64.b64encode(cred.encode()).decode()}


def post_token(api, data, headers=None):
    return api.c.post("/oauth/token", data=data, headers=headers or {})


def exchange(api, client, code_, **over):
    data = {"grant_type": "authorization_code", "code": code_, "redirect_uri": CB, "code_verifier": VERIFIER}
    data.update(over)
    data = {k: v for k, v in data.items() if v is not None}
    if client["client_type"] == "public":
        data["client_id"] = client["client_id"]
        return post_token(api, data)
    return post_token(api, data, basic(client))


def claims_of(db, token, typ=None):
    return keys.verify_jwt(db, token, issuer=settings.OIDC_ISSUER, audience=settings.OIDC_ISSUER if typ else None or "", typ=typ) if typ else None


# ---- happy path and token contents -------------------------------------------------------------

def test_public_client_code_exchange_issues_id_and_access_tokens(db, super_admin, user_api):
    c = mk(super_admin)
    r = exchange(user_api, c, get_code(user_api, c))
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    b = r.json()
    assert b["token_type"] == "Bearer" and b["expires_in"] == settings.OIDC_ACCESS_TOKEN_TTL_SECONDS
    assert b["scope"] == "openid profile email" and "refresh_token" not in b

    idt = keys.verify_jwt(db, b["id_token"], issuer=settings.OIDC_ISSUER, audience=c["client_id"])
    u = user_api.user
    assert idt["sub"] == u.public_id and idt["sub"] != str(u.id) and idt["sub"] != u.email
    assert idt["nonce"] == "nonce-1" and idt["amr"] == ["pwd"] and idt["acr"] == "urn:identityforge:acr:1"
    assert idt["auth_time"] > 0 and idt["email"] == "alice@example.com" and idt["name"] == "Alice Liddell"
    assert idt["zoneinfo"] == "Europe/London" and idt["locale"] == "en-GB"
    assert "department" not in idt and "groups" not in idt                # not granted, not released
    half = hashlib.sha256(b["access_token"].encode()).digest()[:16]
    assert idt["at_hash"] == base64.urlsafe_b64encode(half).rstrip(b"=").decode()

    at = keys.verify_jwt(db, b["access_token"], issuer=settings.OIDC_ISSUER, audience=settings.OIDC_ISSUER, typ="at+jwt")
    assert at["client_id"] == c["client_id"] and at["sub"] == idt["sub"] and at["scope"] == "openid profile email"
    assert at["jti"] and at["tenant"] == "default" and at["exp"] - at["iat"] == settings.OIDC_ACCESS_TOKEN_TTL_SECONDS
    assert db.query(AuditEvent).filter(AuditEvent.action == "OIDC_TOKEN_ISSUED").count() == 1


def test_confidential_client_with_basic_auth(db, super_admin, user_api):
    c = mk(super_admin, client_type="confidential")
    r = exchange(user_api, c, get_code(user_api, c))
    assert r.status_code == 200, r.text


def test_nonce_absent_means_no_nonce_claim(db, super_admin, user_api):
    c = mk(super_admin)
    b = exchange(user_api, c, get_code(user_api, c, nonce=None)).json()
    assert "nonce" not in keys.verify_jwt(db, b["id_token"], issuer=settings.OIDC_ISSUER, audience=c["client_id"])


def test_groups_claim_only_with_groups_scope(db, super_admin, user_api):
    g = super_admin.post("/admin/groups", {"name": "Engineers"}).json()["id"]
    assert super_admin.post(f"/admin/groups/{g}/members", {"user_id": user_api.user.id}).status_code == 201
    c = mk(super_admin)
    b = exchange(user_api, c, get_code(user_api, c, scope="openid groups")).json()
    assert "Engineers" in keys.verify_jwt(db, b["id_token"], issuer=settings.OIDC_ISSUER, audience=c["client_id"])["groups"]


# ---- code binding, PKCE, replay ------------------------------------------------------------------

def test_wrong_verifier_fails_and_burns_the_code(db, super_admin, user_api):
    c = mk(super_admin)
    code = get_code(user_api, c)
    assert exchange(user_api, c, code, code_verifier="x" * 60).json()["error"] == "invalid_grant"
    assert exchange(user_api, c, code).json()["error"] == "invalid_grant"      # right verifier too late: burned


@pytest.mark.parametrize("over", [{"code_verifier": None}, {"code_verifier": "short"}, {"redirect_uri": None}, {"code": None}])
def test_missing_or_malformed_parameters(super_admin, user_api, over):
    c = mk(super_admin)
    assert exchange(user_api, c, get_code(user_api, c), **over).status_code == 400


def test_redirect_uri_must_match_exactly(super_admin, user_api):
    c = mk(super_admin)
    r = exchange(user_api, c, get_code(user_api, c), redirect_uri=CB + "/")
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"


def test_code_is_single_use_and_replay_is_audited(db, super_admin, user_api):
    c = mk(super_admin)
    code = get_code(user_api, c)
    assert exchange(user_api, c, code).status_code == 200
    r = exchange(user_api, c, code)
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"
    assert db.query(AuditEvent).filter(AuditEvent.action == "OIDC_CODE_REPLAY_DETECTED").count() == 1


def test_expired_code_is_refused(db, super_admin, user_api):
    c = mk(super_admin)
    code = get_code(user_api, c)
    row = db.query(AuthorizationCode).one()
    row.expires_at = az.now() - timedelta(seconds=1)
    db.commit()
    assert exchange(user_api, c, code).json()["error"] == "invalid_grant"


def test_code_of_another_client_is_refused_and_not_burned(super_admin, user_api):
    a, b = mk(super_admin), mk(super_admin, name="Other")
    code = get_code(user_api, a)
    assert exchange(user_api, b, code).json()["error"] == "invalid_grant"
    assert exchange(user_api, a, code).status_code == 200                      # the rightful client can still use it


def test_deactivated_user_gets_no_tokens(db, super_admin, user_api):
    c = mk(super_admin)
    code = get_code(user_api, c)
    user_api.user.status = "inactive"
    db.commit()
    assert exchange(user_api, c, code).json()["error"] == "invalid_grant"


def test_unknown_code(super_admin, user_api):
    c = mk(super_admin)
    assert exchange(user_api, c, "nope" * 10).json()["error"] == "invalid_grant"


# ---- client authentication -----------------------------------------------------------------------

def test_confidential_client_needs_its_secret(super_admin, user_api):
    c = mk(super_admin, client_type="confidential")
    code = get_code(user_api, c)
    bad = post_token(user_api, {"grant_type": "authorization_code", "code": code, "redirect_uri": CB, "code_verifier": VERIFIER,
                                "client_id": c["client_id"]})                       # no secret
    assert bad.status_code == 401 and bad.json()["error"] == "invalid_client"
    wrong = {**c, "client_secret": "idf_cs_wrong"}
    r = exchange(user_api, wrong, code)
    assert r.status_code == 401 and r.headers["www-authenticate"].startswith("Basic")
    assert exchange(user_api, c, code).status_code == 200                          # real secret works, code intact


def test_secret_in_body_is_refused(super_admin, user_api):
    c = mk(super_admin, client_type="confidential")
    r = post_token(user_api, {"grant_type": "authorization_code", "code": get_code(user_api, c), "redirect_uri": CB,
                              "code_verifier": VERIFIER, "client_id": c["client_id"], "client_secret": c["client_secret"]})
    assert r.status_code == 400 and r.json()["error"] == "invalid_request"


def test_public_client_cannot_present_a_secret_and_unknown_clients_fail(super_admin, user_api):
    c = mk(super_admin)
    code = get_code(user_api, c)
    r = post_token(user_api, {"grant_type": "authorization_code", "code": code, "redirect_uri": CB, "code_verifier": VERIFIER},
                   basic({**c, "client_secret": "whatever"}))
    assert r.status_code == 401
    ghost = {"client_id": "idf_ghost", "client_type": "public"}
    assert exchange(user_api, ghost, code).status_code == 401


def test_disabled_client_is_refused(super_admin, user_api):
    c = mk(super_admin)
    code = get_code(user_api, c)
    super_admin.patch(f"/admin/oidc/clients/{c['id']}", {"status": "disabled"})
    assert exchange(user_api, c, code).status_code == 401


def test_only_authorization_code_grant_and_form_encoding(super_admin, user_api):
    c = mk(super_admin)
    code = get_code(user_api, c)
    for g in ("password", "implicit"):
        r = exchange(user_api, c, code, grant_type=g)
        assert r.status_code == 400 and r.json()["error"] == "unsupported_grant_type"
    r = exchange(user_api, c, code, grant_type="client_credentials")   # supported, but only for service clients
    assert r.status_code == 400 and r.json()["error"] == "unauthorized_client"
    j = user_api.c.post("/oauth/token", json={"grant_type": "authorization_code"})
    assert j.status_code == 400 and j.json()["error"] == "invalid_request"
    dup = user_api.c.post("/oauth/token", content="grant_type=authorization_code&grant_type=password",
                          headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert dup.status_code == 400


def test_failures_are_rate_limited(super_admin, user_api, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_TOKEN_FAILURES", 3)
    c = mk(super_admin)
    for _ in range(3):
        assert exchange(user_api, c, "bad" * 15).status_code == 400
    assert exchange(user_api, c, "bad" * 15).status_code == 429


def test_signing_not_configured_does_not_burn_the_code(db, super_admin, user_api, monkeypatch):
    c = mk(super_admin)
    code = get_code(user_api, c)

    def boom(*a, **k):
        raise keys.KeyConfigError("no key")

    monkeypatch.setattr(keys, "signing_key", boom)
    assert exchange(user_api, c, code).status_code == 503
    monkeypatch.undo()
    assert exchange(user_api, c, code).status_code == 200           # configuration was checked before the code was spent


# ---- userinfo ---------------------------------------------------------------------------------------

def tokens_for(super_admin, user_api, scope="openid profile email"):
    c = mk(super_admin)
    return c, exchange(user_api, c, get_code(user_api, c, scope=scope)).json()


def test_userinfo_returns_scoped_claims(super_admin, user_api, anon):
    c, t = tokens_for(super_admin, user_api)
    for method in ("get", "post"):
        r = getattr(anon.c, method)("/oauth/userinfo", headers={"Authorization": f"Bearer {t['access_token']}"})
        assert r.status_code == 200, r.text
        assert r.json()["sub"] == user_api.user.public_id and r.json()["email"] == "alice@example.com"
        assert "groups" not in r.json() and "department" not in r.json()


def test_userinfo_rejects_bad_tokens(db, super_admin, user_api, anon):
    c, t = tokens_for(super_admin, user_api)
    h = lambda tok: {"Authorization": f"Bearer {tok}"}
    assert anon.c.get("/oauth/userinfo").status_code == 401
    assert anon.c.get("/oauth/userinfo", params={"access_token": t["access_token"]}).status_code == 401   # not via query
    assert anon.c.get("/oauth/userinfo", headers=h("garbage")).status_code == 401
    assert anon.c.get("/oauth/userinfo", headers=h(t["id_token"])).status_code == 401      # an ID token is not an access token
    tampered = t["access_token"][:-4] + ("AAAA" if not t["access_token"].endswith("AAAA") else "BBBB")
    assert anon.c.get("/oauth/userinfo", headers=h(tampered)).status_code == 401
    r = anon.c.get("/oauth/userinfo", headers=h("garbage"))
    assert 'error="invalid_token"' in r.headers["www-authenticate"]


def test_userinfo_stops_when_user_or_client_is_disabled(db, super_admin, user_api, anon):
    c, t = tokens_for(super_admin, user_api)
    h = {"Authorization": f"Bearer {t['access_token']}"}
    super_admin.patch(f"/admin/oidc/clients/{c['id']}", {"status": "disabled"})
    assert anon.c.get("/oauth/userinfo", headers=h).status_code == 401
    super_admin.patch(f"/admin/oidc/clients/{c['id']}", {"status": "active"})
    user_api.user.status = "inactive"
    db.commit()
    assert anon.c.get("/oauth/userinfo", headers=h).status_code == 401


# ---- discovery -----------------------------------------------------------------------------------------

def test_discovery_document(anon):
    r = anon.c.get("/.well-known/openid-configuration")
    d = r.json()
    assert d["issuer"] == settings.OIDC_ISSUER and d["token_endpoint"].endswith("/oauth/token")
    assert d["response_types_supported"] == ["code"] and d["code_challenge_methods_supported"] == ["S256"]
    assert d["id_token_signing_alg_values_supported"] == ["RS256"]
    assert "offline_access" in d["scopes_supported"] and d["grant_types_supported"] == ["authorization_code", "refresh_token", "client_credentials"] and d["authorization_response_iss_parameter_supported"] is True
    assert anon.c.get(d["jwks_uri"].replace(settings.OIDC_ISSUER, "")).status_code == 200
