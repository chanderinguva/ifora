"""M6: authorize rate limit, purge of expired OIDC rows, non-credentialed CORS."""

from datetime import timedelta

from backend.app.config import settings
from backend.app.oidc import authorize as az, purge
from backend.app.oidc.models import AuthorizationCode, PendingAuthRequest, RefreshToken
from tests.test_oidc_authorize import authorize, params
from tests.test_oidc_refresh import OFFLINE, refresh, start
from tests.test_oidc_token import CB, mk, post_token, user_api  # noqa: F401 (fixture)

ORIGIN = "https://demo.example.com"


# ---- rate limit -----------------------------------------------------------------------------------------

def test_authorize_is_rate_limited_per_ip(monkeypatch, super_admin, user_api):
    monkeypatch.setattr(settings, "RATE_LIMIT_AUTHORIZE_REQUESTS", 3)
    c = mk(super_admin)
    codes = [authorize(user_api, params(c, state=f"s{i}")).status_code for i in range(5)]
    assert codes[:3] == [303, 303, 303] and codes[3:] == [429, 429]


# ---- purge ----------------------------------------------------------------------------------------------

def age(rows, **cols):
    for r in rows:
        for k, v in cols.items():
            setattr(r, k, getattr(r, k) - v)


def test_purge_removes_only_what_can_no_longer_matter(db, super_admin, user_api):
    c, tok = start(super_admin, user_api)                      # live family: refresh token + the code it came from
    live = db.query(RefreshToken).one()
    code = db.query(AuthorizationCode).one()

    # an old pending request and an old unrelated code
    stale_pending = PendingAuthRequest(request_hash="x" * 64, client_pk=live.client_pk, redirect_uri=CB, scopes=["openid"],
                                       code_challenge="c" * 43, expires_at=az.now() - timedelta(days=2))
    fresh_pending = PendingAuthRequest(request_hash="y" * 64, client_pk=live.client_pk, redirect_uri=CB, scopes=["openid"],
                                       code_challenge="c" * 43, expires_at=az.now() + timedelta(minutes=5))
    old_code = AuthorizationCode(code_hash="z" * 64, client_pk=live.client_pk, user_id=live.user_id, redirect_uri=CB,
                                 scopes=["openid"], code_challenge="c" * 43, auth_time=az.now(), amr=["pwd"],
                                 expires_at=az.now() - timedelta(days=3))
    db.add_all([stale_pending, fresh_pending, old_code])
    db.commit()

    out = purge.purge(db)
    assert out == {"pending_requests": 1, "refresh_tokens": 0, "codes": 1, "access_tokens": 0}
    assert db.query(PendingAuthRequest).count() == 1
    assert db.query(RefreshToken).count() == 1                  # live family untouched
    # the code that issued a live refresh token is kept even when it is old, so a replay can still revoke the family
    code.expires_at = az.now() - timedelta(days=30)
    db.commit()
    assert purge.purge(db)["codes"] == 0

    # once the family passes its absolute limit it goes, and then the code does too
    live.absolute_expires_at = az.now() - timedelta(minutes=1)
    db.commit()
    out = purge.purge(db)                                       # same pass: the family first, then the code it pinned
    assert out["refresh_tokens"] == 1 and out["codes"] == 1
    assert db.query(AuthorizationCode).count() == 0


def test_a_rotated_token_in_a_live_family_is_kept_for_reuse_detection(db, super_admin, user_api):
    c, tok = start(super_admin, user_api)
    r = refresh(user_api, c, tok["refresh_token"])
    assert r.status_code == 200
    assert db.query(RefreshToken).count() == 2
    for row in db.query(RefreshToken).all():
        row.expires_at = az.now() - timedelta(days=10)          # idle-expired but the family is still within its limit
    db.commit()
    assert purge.purge(db)["refresh_tokens"] == 0
    assert refresh(user_api, c, tok["refresh_token"]).status_code == 400   # reuse is still recognised (and refused)


# ---- CORS -----------------------------------------------------------------------------------------------

def exchange_from(api, client, origin):
    from tests.test_oidc_token import VERIFIER, get_code
    data = {"grant_type": "authorization_code", "code": get_code(api, client), "redirect_uri": CB,
            "code_verifier": VERIFIER, "client_id": client["client_id"]}
    return api.c.post("/oauth/token", data=data, headers={"Origin": origin})


def test_public_client_token_endpoint_allows_only_its_own_origin(super_admin, user_api):
    c = mk(super_admin)
    ok = exchange_from(user_api, c, ORIGIN)
    assert ok.status_code == 200
    assert ok.headers["access-control-allow-origin"] == ORIGIN
    assert "access-control-allow-credentials" not in ok.headers
    other = exchange_from(user_api, c, "https://evil.example.com")
    assert "access-control-allow-origin" not in other.headers


def test_token_cors_is_not_granted_to_confidential_clients(super_admin, user_api):
    from tests.test_oidc_token import VERIFIER, basic, get_code
    c = mk(super_admin, client_type="confidential")
    r = user_api.c.post("/oauth/token", data={"grant_type": "authorization_code", "code": get_code(user_api, c), "redirect_uri": CB,
                                              "code_verifier": VERIFIER}, headers={**basic(c), "Origin": ORIGIN})
    assert r.status_code == 200 and "access-control-allow-origin" not in r.headers


def test_token_preflight(super_admin, user_api):
    c = mk(super_admin)
    p = user_api.c.options("/oauth/token", headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST"})
    assert p.status_code == 204 and p.headers["access-control-allow-origin"] == ORIGIN
    assert p.headers["access-control-allow-methods"] == "POST" and "credentials" not in str(p.headers).lower()
    bad = user_api.c.options("/oauth/token", headers={"Origin": "https://evil.example.com", "Access-Control-Request-Method": "POST"})
    assert bad.status_code == 204 and "access-control-allow-origin" not in bad.headers


def test_userinfo_and_jwks_are_readable_from_any_origin_without_credentials(user_api):
    p = user_api.c.options("/oauth/userinfo", headers={"Origin": "https://x.example.com", "Access-Control-Request-Method": "GET"})
    assert p.status_code == 204 and p.headers["access-control-allow-origin"] == "*"
    assert "authorization" in p.headers["access-control-allow-headers"].lower()
    r = user_api.c.get("/oauth/userinfo", headers={"Origin": "https://x.example.com"})
    assert r.status_code == 401 and r.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in r.headers
    assert user_api.c.get("/oauth/jwks").headers["access-control-allow-origin"] == "*"
