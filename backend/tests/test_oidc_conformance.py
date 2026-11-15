"""IFORA-24: the OIDC conformance matrix is checked against the live discovery document, and an independent client
library (authlib) completes the whole flow against the running app over real HTTP.

The matrix itself is data in `oidc_matrix.py`; `scripts/oidc_matrix.py` runs the tests it names and writes the document.
"""

import ast
import socket
import threading
import time
from pathlib import Path

import httpx
import pytest

from backend.app.config import settings
from tests import oidc_matrix as M
from tests.conftest import ORIGIN, STRONG, make_user
from tests.test_oidc_authorize import CB
from tests.test_oidc_refresh import SCOPES, mk
from tests.test_oidc_token import user_api  # noqa: F401  (fixture)

TESTS = Path(__file__).resolve().parent


def _discovery(anon):
    r = anon.c.get("/.well-known/openid-configuration")
    assert r.status_code == 200
    return r.json()


# --- the matrix describes tests that exist ---------------------------------------------------------------------------


def test_every_test_the_matrix_names_exists():
    missing = []
    for row in M.ROWS:
        assert row.tests, f"{row.id} names no test"
        for ref in row.tests:
            path, _, name = ref.partition("::")
            f = TESTS / path
            if not f.exists():
                missing.append(ref)
                continue
            tree = ast.parse(f.read_text())
            if name not in {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}:
                missing.append(ref)
    assert not missing, missing


def test_row_ids_are_unique_and_statuses_known():
    ids = [r.id for r in M.ROWS]
    assert len(ids) == len(set(ids))
    assert {r.status for r in M.ROWS} <= {"supported", "not-supported"}


# --- discovery advertises exactly what the matrix covers -------------------------------------------------------------


def test_every_advertised_feature_has_a_matrix_row(anon):
    d = _discovery(anon)
    row_ids = {r.id for r in M.ROWS}
    uncovered = sorted(k for k in d if k not in M.DISCOVERY_COVERAGE)
    assert not uncovered, f"advertised without a matrix row: {uncovered}"
    for key, rows in M.DISCOVERY_COVERAGE.items():
        assert set(rows) <= row_ids, (key, rows)
        assert key in d, f"the matrix says '{key}' is advertised but discovery omits it"
    for key, allowed in M.SUPPORTED_VALUES.items():
        extra = set(d[key]) - set(allowed)
        assert not extra, f"{key} advertises values with no matrix row: {sorted(extra)}"
        assert set(allowed) <= set(d[key]), f"{key} no longer advertises {sorted(set(allowed) - set(d[key]))}"


def test_unsupported_features_are_not_advertised(anon):
    d = _discovery(anon)
    assert not [k for k in M.UNSUPPORTED_KEYS if k in d]
    assert not set(M.UNSUPPORTED_GRANTS) & set(d["grant_types_supported"])
    assert d["claims_parameter_supported"] is False and d["request_parameter_supported"] is False
    assert d["request_uri_parameter_supported"] is False
    assert d["code_challenge_methods_supported"] == ["S256"]  # never "plain"


def test_discovery_matches_the_issuer_that_served_it(anon):
    d = _discovery(anon)
    iss = d["issuer"].rstrip("/")
    for key in ("authorization_endpoint", "token_endpoint", "userinfo_endpoint", "jwks_uri", "revocation_endpoint",
                "introspection_endpoint", "end_session_endpoint"):
        assert d[key].startswith(iss + "/"), key
    path = lambda u: u[len(iss):]  # noqa: E731
    # every advertised endpoint is really routed (a wrong method or missing credentials is an answer; 404 is not)
    assert anon.c.get(path(d["authorization_endpoint"])).status_code != 404
    assert anon.c.post(path(d["token_endpoint"]), data={}).status_code in (400, 401)
    assert anon.c.get(path(d["userinfo_endpoint"])).status_code == 401
    assert anon.c.get(path(d["jwks_uri"])).status_code == 200
    assert anon.c.post(path(d["revocation_endpoint"]), data={"token": "x"}).status_code != 404
    assert anon.c.post(path(d["introspection_endpoint"]), data={"token": "x"}).status_code in (400, 401)
    assert anon.c.get(path(d["end_session_endpoint"]), follow_redirects=False).status_code == 303
    algs = {k["alg"] for k in anon.c.get(path(d["jwks_uri"])).json()["keys"]}
    assert set(d["id_token_signing_alg_values_supported"]) == algs  # advertised algorithms are the published ones


# --- an independent client over real HTTP ----------------------------------------------------------------------------


@pytest.fixture
def live_server(monkeypatch):
    """The real app on a real socket in this process (same database), so an external HTTP client can talk to it."""
    import uvicorn

    from backend.app.api import app

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    base = f"http://127.0.0.1:{sock.getsockname()[1]}"
    monkeypatch.setattr(settings, "OIDC_ISSUER", base)
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="off"))
    t = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started
    yield base
    server.should_exit = True
    t.join(timeout=5)
    sock.close()


def test_an_independent_client_completes_the_whole_flow_over_http(db, super_admin, live_server):
    from authlib.common.security import generate_token
    from authlib.integrations.base_client import OAuthError
    from authlib.integrations.httpx_client import OAuth2Client
    from authlib.jose import JsonWebKey, jwt
    from authlib.oidc.core import CodeIDToken

    base = live_server
    c = mk(super_admin)
    user = make_user(db, "interop@example.com")

    disc = httpx.get(base + "/.well-known/openid-configuration").json()
    assert disc["issuer"] == base

    rp = OAuth2Client(client_id=c["client_id"], redirect_uri=CB, scope="openid profile email offline_access",
                      code_challenge_method="S256", token_endpoint_auth_method="none")
    verifier, nonce = generate_token(48), generate_token(16)
    url, state = rp.create_authorization_url(disc["authorization_endpoint"], code_verifier=verifier, nonce=nonce)

    with httpx.Client(follow_redirects=False) as browser:  # the user's browser: sign in, then follow the authorize URL
        r = browser.post(base + "/api/v1/login", json={"email": user.email, "password": STRONG}, headers={"Origin": ORIGIN})
        assert r.status_code == 200, r.text
        r = browser.get(url)
        assert r.status_code == 303 and r.headers["location"].startswith(CB), r.text
        callback = r.headers["location"]

    # 1. code + PKCE
    token = rp.fetch_token(disc["token_endpoint"], authorization_response=callback, state=state, code_verifier=verifier)
    assert token["token_type"].lower() == "bearer" and token["access_token"] and token["refresh_token"]
    assert "iss=" in callback  # RFC 9207: the authorization response names its issuer

    # 2. the ID token validates against the published JWKS, issuer, audience, nonce and at_hash, by authlib's own checks
    jwks = JsonWebKey.import_key_set(httpx.get(disc["jwks_uri"]).json())
    claims = jwt.decode(token["id_token"], jwks, claims_cls=CodeIDToken,
                        claims_options={"iss": {"values": [base]}, "aud": {"values": [c["client_id"]]}},
                        claims_params={"nonce": nonce, "access_token": token["access_token"]})
    claims.validate()
    assert claims["sub"] and claims["nonce"] == nonce and "at_hash" in claims

    # 3. userinfo
    info = rp.get(disc["userinfo_endpoint"], headers={"Authorization": "Bearer " + token["access_token"]})
    assert info.status_code == 200 and info.json()["sub"] == claims["sub"] and info.json()["email"] == user.email

    # 4. refresh rotates; the spent token is dead (reuse detection ends the family)
    new = rp.refresh_token(disc["token_endpoint"], refresh_token=token["refresh_token"])
    assert new["access_token"] != token["access_token"] and new["refresh_token"] != token["refresh_token"]
    with pytest.raises(OAuthError) as e:
        rp.refresh_token(disc["token_endpoint"], refresh_token=token["refresh_token"])
    assert e.value.error == "invalid_grant"

    # 5. the family was revoked by the reuse, so even the newest token is dead (RFC 6749 BCP: rotation with reuse detection)
    with pytest.raises(OAuthError):
        rp.refresh_token(disc["token_endpoint"], refresh_token=new["refresh_token"])

    # 6. revocation endpoint (RFC 7009) via the advertised URL: a fresh grant, revoked, no longer refreshes
    verifier2, nonce2 = generate_token(48), generate_token(16)
    url2, state2 = rp.create_authorization_url(disc["authorization_endpoint"], code_verifier=verifier2, nonce=nonce2)
    with httpx.Client(follow_redirects=False) as browser:
        browser.post(base + "/api/v1/login", json={"email": user.email, "password": STRONG}, headers={"Origin": ORIGIN})
        cb2 = browser.get(url2).headers["location"]
    t2 = rp.fetch_token(disc["token_endpoint"], authorization_response=cb2, state=state2, code_verifier=verifier2)
    rp.revoke_token(disc["revocation_endpoint"], token=t2["refresh_token"], token_type_hint="refresh_token")
    with pytest.raises(OAuthError):
        rp.refresh_token(disc["token_endpoint"], refresh_token=t2["refresh_token"])
    rp.close()
