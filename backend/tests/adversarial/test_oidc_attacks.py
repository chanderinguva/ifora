"""IFORA-17: adversarial regression suite for the OIDC provider. Each test names the attack and its register ID / CWE.

Real app, real database, real signatures; nothing here weakens production settings. A test that fails is a finding:
report it, do not skip it.
"""

import base64
import hashlib
import json
import time
import uuid
from urllib.parse import parse_qs, urlsplit

import pytest
from joserfc import jwt
from joserfc.jwk import ECKey, OctKey

from backend.app.config import settings
from backend.app.oidc import client_auth
from backend.app.oidc.models import AuthorizationCode, RefreshToken
from tests.conftest import Api
from tests.test_oidc_pkjwt_es256 import TOKEN_URL, assertion, code_exchange, form, mk_pk, pub  # noqa: F401
from tests.test_oidc_refresh import refresh, start
from tests.test_oidc_token import CB, CHALLENGE, VERIFIER, exchange, get_code, mk, post_token, user_api  # noqa: F401

pytestmark = pytest.mark.adversarial


def _b64(d: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(d, separators=(",", ":")).encode()).rstrip(b"=").decode()


def _bearer(tok):
    return {"Authorization": f"Bearer {tok}"}


def _authorize(api, client, **over):
    p = {"client_id": client["client_id"], "redirect_uri": CB, "response_type": "code", "scope": "openid profile",
         "state": "s", "nonce": "n", "code_challenge": CHALLENGE, "code_challenge_method": "S256", **over}
    return api.c.get("/oauth/authorize", params={k: v for k, v in p.items() if v is not None}, follow_redirects=False)


def _issued_code(r) -> bool:
    loc = r.headers.get("location", "")
    return "code" in parse_qs(urlsplit(loc).query)


# ---- PKCE (RFC 7636 / OAuth 2.1; CWE-345, CWE-303) ----------------------------------------------------------------


@pytest.mark.parametrize("over", [
    {"code_challenge": None, "code_challenge_method": None},            # no PKCE at all (downgrade)
    {"code_challenge": None},                                           # method without a challenge
    {"code_challenge_method": "plain"},                                 # downgrade to plain
    {"code_challenge_method": "s256"},                                  # case games
    {"code_challenge_method": None},                                    # default method is plain in RFC 7636
    {"code_challenge": "short"},                                        # below the 43-char minimum
    {"code_challenge": "!" * 43},                                       # not base64url
])
def test_pkce_downgrade_attempts_never_issue_a_code(db, super_admin, user_api, over):
    """PKCE downgrade / missing challenge (CWE-345): the authorization endpoint refuses and stores no code."""
    c = mk(super_admin)
    r = _authorize(user_api, c, **over)
    assert not _issued_code(r), r.headers.get("location")
    assert db.query(AuthorizationCode).count() == 0


@pytest.mark.parametrize("verifier", [None, "", "x" * 60, VERIFIER[:-1], VERIFIER + "A", VERIFIER.upper(), "a" * 10, "é" * 50])
def test_wrong_or_missing_code_verifier_gets_invalid_grant_and_no_token(db, super_admin, user_api, verifier):
    """AC1 / PKCE verifier bypass (CWE-303): wrong, missing, truncated or altered verifier -> no token."""
    c = mk(super_admin)
    r = exchange(user_api, c, get_code(user_api, c), code_verifier=verifier)
    assert r.status_code == 400 and r.json()["error"] in ("invalid_grant", "invalid_request")
    assert "access_token" not in r.text and "id_token" not in r.text


def test_a_failed_verifier_burns_the_code_so_it_cannot_be_guessed_at(db, super_admin, user_api):
    """Online guessing of the verifier (CWE-307): one wrong try spends the code; the right verifier then fails too."""
    c = mk(super_admin)
    code = get_code(user_api, c)
    assert exchange(user_api, c, code, code_verifier="y" * 60).status_code == 400
    r = exchange(user_api, c, code)
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"


# ---- redirect_uri variants (RFC 9700 4.1; CWE-601) ----------------------------------------------------------------


@pytest.mark.parametrize("uri", [
    CB + "/", CB.upper(), CB + "?x=1", CB + "#frag", "http://demo.example.com/callback",
    "https://demo.example.com@evil.example.com/callback", "https://demo.example.com.evil.example.com/callback",
    "https://evil.example.com/callback", "https://sub.demo.example.com/callback", "https://demo.example.com/callback/../x",
    "https://demo.example.com/%63allback", "https://demo.example.com:443/callback", "https://demo.example.com/callback%0d%0aX: y",
    "javascript:alert(1)", "//evil.example.com/callback", "https://demo.example.com\\@evil.example.com/callback",
])
def test_redirect_uri_must_match_a_registered_value_exactly(db, super_admin, user_api, uri):
    """Open redirect / redirect_uri tampering (CWE-601): never redirect, never issue a code, for any variant."""
    c = mk(super_admin)
    r = _authorize(user_api, c, redirect_uri=uri)
    assert r.status_code != 303 or not r.headers["location"].startswith(uri.split("?")[0]), r.headers.get("location")
    assert not _issued_code(r)
    assert "evil.example.com" not in r.headers.get("location", "")
    assert db.query(AuthorizationCode).count() == 0


def test_redirect_uri_at_exchange_must_equal_the_one_authorized(db, super_admin, user_api):
    """redirect_uri swap between authorize and token (RFC 6749 4.1.3, CWE-601)."""
    c = mk(super_admin, redirect_uris=[CB, "https://demo.example.com/other"])
    r = exchange(user_api, c, get_code(user_api, c), redirect_uri="https://demo.example.com/other")
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"


# ---- code and refresh token reuse (CWE-294, CWE-613) ----------------------------------------------------------------


def test_authorization_code_replay_is_refused_and_revokes_what_it_produced(db, super_admin, user_api):
    """Code replay (RFC 6749 4.1.2; CWE-294): the second use fails and tokens already issued from it are revoked."""
    c, first = start(super_admin, user_api, client_type="confidential")
    code = get_code(user_api, c, scope="openid profile offline_access")
    ok = exchange(user_api, c, code)
    assert ok.status_code == 200
    replay = exchange(user_api, c, code)
    assert replay.status_code == 400 and replay.json()["error"] == "invalid_grant"
    assert refresh(user_api, c, ok.json()["refresh_token"]).status_code == 400


def test_code_cannot_be_redeemed_by_another_client(db, super_admin, user_api):
    """Code injection across clients (RFC 9700 4.5; CWE-639)."""
    a = mk(super_admin, name="A", client_type="confidential")
    b = mk(super_admin, name="B", client_type="confidential")
    r = exchange(user_api, b, get_code(user_api, a))
    assert r.status_code == 400 and "access_token" not in r.text


def test_a_rotated_refresh_token_presented_again_revokes_the_whole_family(db, super_admin, user_api):
    """AC2 / refresh token theft (RFC 9700 4.14; CWE-294)."""
    c, first = start(super_admin, user_api)
    second = refresh(user_api, c, first["refresh_token"]).json()
    r = refresh(user_api, c, first["refresh_token"])
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"
    assert refresh(user_api, c, second["refresh_token"]).status_code == 400
    assert db.query(RefreshToken).filter(RefreshToken.revoked_at.is_(None)).count() == 0


def test_refresh_cannot_widen_scope_or_cross_clients(db, super_admin, user_api):
    """Scope escalation on refresh (CWE-269) and cross-client refresh (CWE-639)."""
    c, body = start(super_admin, user_api)
    assert refresh(user_api, c, body["refresh_token"], scope="openid profile offline_access email").status_code == 400
    other = mk(super_admin, name="Other", allowed_scopes=["openid", "profile", "email", "offline_access"])
    r = refresh(user_api, other, body["refresh_token"])
    assert r.status_code == 400 and "refresh_token" not in r.text


def test_unassigned_user_cannot_keep_minting_tokens(db, super_admin, user_api):
    """SEC-B-1 (fixed by IFORA-47): assignment is rechecked on refresh, not only at authorize."""
    from tests.test_oidc_opaque import _require_assignment

    c, body = start(super_admin, user_api, client_type="confidential")
    _require_assignment(super_admin)
    r = refresh(user_api, c, body["refresh_token"])
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"


# ---- token confusion and forged JWTs (CWE-347, CWE-345) -------------------------------------------------------------


def _tokens(super_admin, user_api):
    c = mk(super_admin)
    r = exchange(user_api, c, get_code(user_api, c))
    assert r.status_code == 200
    return c, r.json()


def _forge_none(token: str, **claim_over) -> str:
    h, p, _ = token.split(".")
    payload = json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))
    payload.update(claim_over)
    return f"{_b64({'alg': 'none', 'typ': 'at+jwt'})}.{_b64(payload)}."


def test_userinfo_rejects_unsigned_confused_and_tampered_tokens(db, super_admin, user_api, anon):
    """alg=none, HS256-with-public-key confusion, payload tampering, ID token as access token (CWE-347)."""
    c, t = _tokens(super_admin, user_api)
    at = t["access_token"]
    hdr = json.loads(base64.urlsafe_b64decode(at.split(".")[0] + "=" * (-len(at.split(".")[0]) % 4)))
    claims = json.loads(base64.urlsafe_b64decode(at.split(".")[1] + "=" * (-len(at.split(".")[1]) % 4)))
    from backend.app.oidc import keys

    pubkey = json.dumps(keys.public_jwks(db)["keys"][0]).encode()
    hs = jwt.encode({"alg": "HS256", "kid": hdr["kid"], "typ": "at+jwt"}, claims, OctKey.import_key(pubkey.ljust(32, b"x")), algorithms=["HS256"])
    p = at.split(".")
    flipped = f"{p[0]}.{_b64({**claims, 'sub': 'someone-else'})}.{p[2]}"
    for bad in (_forge_none(at), hs, flipped, t["id_token"], at + "x", "a.b.c", "", "Bearer"):
        r = anon.c.get("/oauth/userinfo", headers=_bearer(bad))
        assert r.status_code == 401, bad[:30]
        assert "sub" not in r.text


def test_expired_and_wrong_audience_access_tokens_are_refused(db, super_admin, user_api, anon):
    """Expired / wrong-aud token acceptance (CWE-613, CWE-345): signed by us, but not valid for this use."""
    from backend.app.oidc import keys

    c, t = _tokens(super_admin, user_api)
    claims = jwt.decode(t["access_token"], keys.KeySet.import_key_set(keys.public_jwks(db)), algorithms=["RS256", "ES256"]).claims
    for over in ({"exp": int(time.time()) - 3600}, {"aud": "https://evil.example.com"}, {"iss": "https://evil.example.com"}):
        tok = keys.sign_jwt(db, {**claims, **over}, typ="at+jwt")
        assert anon.c.get("/oauth/userinfo", headers=_bearer(tok)).status_code == 401, over


def test_refresh_and_access_tokens_are_not_interchangeable(db, super_admin, user_api, anon):
    """Token type confusion (CWE-345): an access token is no refresh token and vice versa."""
    c, body = start(super_admin, user_api)
    assert refresh(user_api, c, body["access_token"]).status_code == 400
    assert anon.c.get("/oauth/userinfo", headers=_bearer(body["refresh_token"])).status_code == 401


def test_oversized_and_malformed_token_requests_are_refused_cleanly(db, super_admin, user_api):
    """Huge / malformed input (CWE-400, CWE-20): a 4xx with an OAuth error, never a 5xx or a stack trace."""
    c = mk(super_admin)
    for data in ({"grant_type": "authorization_code", "code": "A" * 200_000, "redirect_uri": CB, "code_verifier": VERIFIER,
                  "client_id": c["client_id"]},
                 {"grant_type": "authorization_code", "code": "\x00\x01", "client_id": c["client_id"]},
                 {"grant_type": "refresh_token", "refresh_token": "ey" * 50_000, "client_id": c["client_id"]}):
        r = post_token(user_api, data)
        assert 400 <= r.status_code < 500 and "Traceback" not in r.text and "access_token" not in r.text


# ---- private_key_jwt client authentication (RFC 7523; CWE-347, CWE-294) ----------------------------------------------


@pytest.fixture(scope="module")
def ec():
    return ECKey.generate_key("P-256")


@pytest.fixture(scope="module")
def other_ec():
    return ECKey.generate_key("P-256")


def _unsigned_assertion(client) -> str:
    t = int(time.time())
    claims = {"iss": client["client_id"], "sub": client["client_id"], "aud": TOKEN_URL, "iat": t, "exp": t + 60, "jti": str(uuid.uuid4())}
    return f"{_b64({'alg': 'none', 'kid': 'k1'})}.{_b64(claims)}."


def test_client_assertion_attacks_are_all_refused(db, super_admin, user_api, ec, other_ec):
    """alg=none, alg confusion, wrong key, wrong aud/iss/sub, expired, no jti (CWE-347, RFC 7523 3)."""
    c = mk_pk(super_admin, ec)
    secret_from_public = OctKey.import_key(json.dumps(pub(ec, "k1")).encode().ljust(32, b"x"))
    t = int(time.time())
    base = {"iss": c["client_id"], "sub": c["client_id"], "aud": TOKEN_URL, "iat": t, "exp": t + 60, "jti": str(uuid.uuid4())}
    attacks = {
        "alg none": _unsigned_assertion(c),
        "HS256 with the public key as secret": jwt.encode({"alg": "HS256", "kid": "k1"}, base, secret_from_public, algorithms=["HS256"]),
        "signed by another key": assertion(c, other_ec),
        "wrong audience": assertion(c, ec, aud="https://evil.example.com/oauth/token"),
        "wrong issuer": assertion(c, ec, iss="someone-else"),
        "sub differs from iss": assertion(c, ec, sub="someone-else"),
        "expired": assertion(c, ec, iat=t - 600, exp=t - 300),
        "no jti": assertion(c, ec, jti=None),
        "no exp": assertion(c, ec, exp=None),
        "garbage": "not.a.jwt",
        "huge": "e" * 300_000,
    }
    for name, a in attacks.items():
        r = code_exchange(user_api, c, a)
        assert r.status_code in (400, 401), name
        assert "access_token" not in r.text, name


def test_client_assertion_cannot_be_replayed(db, super_admin, user_api, ec):
    """jti replay (RFC 7523 3 / CWE-294): the same signed assertion is accepted once."""
    c = mk_pk(super_admin, ec)
    a = assertion(c, ec)
    assert code_exchange(user_api, c, a).status_code == 200
    r = code_exchange(user_api, c, a)
    assert r.status_code in (400, 401) and "access_token" not in r.text


# ---- state / nonce handling (CWE-352, CWE-113) --------------------------------------------------------------------------


def test_state_is_echoed_verbatim_and_cannot_inject_headers_or_parameters(db, super_admin, user_api):
    """CRLF / parameter injection through state (CWE-113, CWE-601): the redirect stays on the registered URI."""
    c = mk(super_admin)
    nasty = "a%0d%0aSet-Cookie:x=1&code=forged#frag?x"
    r = _authorize(user_api, c, state=nasty)
    assert r.status_code == 303
    loc = r.headers["location"]
    assert loc.startswith(CB + "?") and "\r" not in loc and "\n" not in loc
    q = parse_qs(urlsplit(loc).query)
    assert q["state"] == [nasty] and len(q["code"]) == 1 and "Set-Cookie" not in r.headers


def test_nonce_is_bound_into_the_id_token_unchanged(db, super_admin, user_api):
    """Nonce replay protection (OIDC Core 3.1.3.7): the value sent is the value signed."""
    from backend.app.oidc import keys

    c = mk(super_admin)
    n = "nonce-" + uuid.uuid4().hex
    r = exchange(user_api, c, get_code(user_api, c, nonce=n))
    idt = keys.verify_jwt(db, r.json()["id_token"], issuer=settings.OIDC_ISSUER, audience=c["client_id"])
    assert idt["nonce"] == n


def test_huge_state_or_nonce_does_not_break_the_endpoint(db, super_admin, user_api):
    """Oversized parameters (CWE-400): handled as an error or truncated safely, never a 5xx."""
    c = mk(super_admin)
    for over in ({"state": "s" * 40_000}, {"nonce": "n" * 40_000}):
        r = _authorize(user_api, c, **over)
        assert r.status_code < 500
