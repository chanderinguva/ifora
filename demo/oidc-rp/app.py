"""Demo OIDC relying party: a separate, third-party web app that signs users in with Ifora.

Confidential client, authorization code + PKCE (S256), state/nonce, ID token validation against the
provider's JWKS, UserInfo, refresh, revocation and RP-initiated logout. Sessions live in memory: this is a
demonstration of the protocol, not a template for production session handling.

Browser-facing URLs use ISSUER (what the user's browser can reach); server-to-server calls use INTERNAL_ISSUER
(the compose network name). Token `iss` is always validated against ISSUER.
"""

import base64
import hashlib
import html
import json
import os
import secrets
import time
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet
from joserfc.jwt import JWTClaimsRegistry

ISSUER = os.environ.get("ISSUER", "http://localhost:8000").rstrip("/")
INTERNAL = os.environ.get("INTERNAL_ISSUER", ISSUER).rstrip("/")
BASE_URL = os.environ.get("BASE_URL", "http://localhost:4000").rstrip("/")
SCOPES = os.environ.get("SCOPES", "openid profile email offline_access")
CONFIG = {"client_id": os.environ.get("CLIENT_ID", ""), "client_secret": os.environ.get("CLIENT_SECRET", "")}
ALLOW_CONFIG = os.environ.get("DEMO_ALLOW_CONFIG") == "1"  # lets the e2e suite inject credentials; off by default

COOKIE = "demo_sid"
SESSIONS: dict[str, dict] = {}  # sid -> {user claims, tokens}
TX: dict[str, dict] = {}        # state -> {verifier, nonce, created}
TX_TTL = 600

app = FastAPI(title="Ifora demo app", docs_url=None, redoc_url=None, openapi_url=None)


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def page(body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
        "<title>Demo app</title><style>body{font:16px/1.5 system-ui;max-width:42rem;margin:3rem auto;padding:0 1rem}"
        "pre{background:#f4f4f5;padding:.75rem;overflow:auto;border-radius:6px}button,a.b{font:inherit;padding:.4rem .9rem;"
        "border:1px solid #888;border-radius:6px;background:#fff;text-decoration:none;color:inherit;cursor:pointer}"
        "form{display:inline}.err{color:#b91c1c}</style><h1>Demo app</h1>" + body,
        status_code=status,
        headers={"Cache-Control": "no-store"},
    )


def current(request: Request) -> Optional[dict]:
    return SESSIONS.get(request.cookies.get(COOKIE, ""))


def configured() -> bool:
    return bool(CONFIG["client_id"] and CONFIG["client_secret"])


def esc(v) -> str:
    return html.escape(str(v))


async def jwks() -> KeySet:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{INTERNAL}/oauth/jwks")
        r.raise_for_status()
    return KeySet.import_key_set(r.json())


async def verify_id_token(token: str, nonce: Optional[str]) -> dict:
    decoded = jwt.decode(token, await jwks(), algorithms=["RS256"])
    checks = {"iss": {"essential": True, "value": ISSUER}, "aud": {"essential": True, "value": CONFIG["client_id"]},
              "exp": {"essential": True}, "sub": {"essential": True}}
    if nonce is not None:
        checks["nonce"] = {"essential": True, "value": nonce}
    JWTClaimsRegistry(leeway=60, **checks).validate(decoded.claims)
    return decoded.claims


async def token_call(data: dict) -> httpx.Response:
    async with httpx.AsyncClient(timeout=10) as c:
        return await c.post(f"{INTERNAL}/oauth/token", data=data, auth=(CONFIG["client_id"], CONFIG["client_secret"]))


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/_config")
async def set_config(request: Request):
    """Test hook: only when DEMO_ALLOW_CONFIG=1."""
    if not ALLOW_CONFIG:
        return JSONResponse({"detail": "disabled"}, status_code=404)
    body = await request.json()
    CONFIG["client_id"], CONFIG["client_secret"] = str(body["client_id"]), str(body["client_secret"])
    SESSIONS.clear()
    TX.clear()
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    s = current(request)
    if not configured():
        return page("<p data-testid=unconfigured>Not configured. Register this app as an application in Ifora "
                    f"(redirect URI <code>{esc(BASE_URL)}/callback</code>, post-logout URI <code>{esc(BASE_URL)}/signed-out</code>) "
                    "and set <code>CLIENT_ID</code> and <code>CLIENT_SECRET</code>.</p>")
    if not s:
        return page("<p data-testid=signed-out>You are not signed in.</p><p><a class=b data-testid=signin href='/login'>Sign in with Ifora</a></p>")
    notice = f"<p data-testid=notice>{esc(s.pop('notice'))}</p>" if s.get("notice") else ""
    return page(
        f"<p data-testid=welcome>Signed in as <strong>{esc(s['claims'].get('name') or s['claims']['sub'])}</strong></p>{notice}"
        f"<h3>ID token claims</h3><pre data-testid=claims>{esc(json.dumps(s['claims'], indent=2, sort_keys=True))}</pre>"
        f"<h3>UserInfo</h3><pre data-testid=userinfo>{esc(json.dumps(s['userinfo'], indent=2, sort_keys=True))}</pre>"
        f"<p>Refresh token: <strong data-testid=refresh-state>{'held' if s.get('refresh_token') else 'none'}</strong></p>"
        "<form method=post action=/refresh><button data-testid=refresh>Refresh tokens</button></form> "
        "<form method=post action=/revoke><button data-testid=revoke>Revoke refresh token</button></form> "
        "<form method=post action=/logout><button data-testid=logout>Sign out</button></form>"
    )


@app.get("/login")
def login(request: Request, prompt: Optional[str] = None):
    if not configured():
        return RedirectResponse("/", status_code=303)
    now = time.time()
    for k in [k for k, v in TX.items() if now - v["created"] > TX_TTL]:
        TX.pop(k, None)
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    TX[state] = {"verifier": verifier, "nonce": nonce, "created": now}
    q = {
        "client_id": CONFIG["client_id"], "redirect_uri": f"{BASE_URL}/callback", "response_type": "code", "scope": SCOPES,
        "state": state, "nonce": nonce, "code_challenge": b64u(hashlib.sha256(verifier.encode()).digest()),
        "code_challenge_method": "S256",
    }
    if prompt in ("login", "consent", "none"):
        q["prompt"] = prompt
    return RedirectResponse(f"{ISSUER}/oauth/authorize?{urlencode(q)}", status_code=303)


@app.get("/callback")
async def callback(request: Request, code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None,
                   error_description: Optional[str] = None, iss: Optional[str] = None):
    tx = TX.pop(state or "", None)
    if tx is None:
        return page("<p class=err data-testid=error>Unknown or expired sign-in attempt.</p><p><a class=b href='/'>Back</a></p>", 400)
    if iss is not None and iss != ISSUER:  # RFC 9207 mix-up defence
        return page("<p class=err data-testid=error>Response came from an unexpected issuer.</p>", 400)
    if error:
        return page(f"<p class=err data-testid=error>Sign-in was not completed: <code data-testid=error-code>{esc(error)}</code></p>"
                    "<p><a class=b href='/'>Back</a></p>", 200)
    if not code:
        return page("<p class=err data-testid=error>Missing code.</p>", 400)
    r = await token_call({"grant_type": "authorization_code", "code": code, "redirect_uri": f"{BASE_URL}/callback",
                          "code_verifier": tx["verifier"]})
    if r.status_code != 200:
        return page(f"<p class=err data-testid=error>Token request failed: {esc(r.json().get('error', r.status_code))}</p>", 502)
    tok = r.json()
    try:
        claims = await verify_id_token(tok["id_token"], tx["nonce"])
    except (JoseError, ValueError, KeyError):
        return page("<p class=err data-testid=error>The ID token could not be validated.</p>", 502)
    async with httpx.AsyncClient(timeout=10) as c:
        ui = await c.get(f"{INTERNAL}/oauth/userinfo", headers={"Authorization": f"Bearer {tok['access_token']}"})
    userinfo = ui.json() if ui.status_code == 200 else {"error": ui.status_code}
    if userinfo.get("sub") != claims["sub"]:
        return page("<p class=err data-testid=error>UserInfo subject mismatch.</p>", 502)
    sid = secrets.token_urlsafe(32)
    SESSIONS[sid] = {"claims": claims, "userinfo": userinfo, "id_token": tok["id_token"], "access_token": tok["access_token"],
                     "refresh_token": tok.get("refresh_token")}
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(COOKIE, sid, httponly=True, samesite="lax", path="/")
    return resp


@app.post("/refresh")
async def refresh(request: Request):
    s = current(request)
    if not s or not s.get("refresh_token"):
        return RedirectResponse("/", status_code=303)
    r = await token_call({"grant_type": "refresh_token", "refresh_token": s["refresh_token"]})
    if r.status_code != 200:
        s["refresh_token"] = None
        s["notice"] = f"Refresh failed: {r.json().get('error', r.status_code)}"
    else:
        tok = r.json()
        s["access_token"], s["refresh_token"] = tok["access_token"], tok.get("refresh_token", s["refresh_token"])
        s["notice"] = "Tokens refreshed."
    return RedirectResponse("/", status_code=303)


@app.post("/revoke")
async def revoke(request: Request):
    s = current(request)
    if s and s.get("refresh_token"):
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(f"{INTERNAL}/oauth/revoke", data={"token": s["refresh_token"], "token_type_hint": "refresh_token"},
                         auth=(CONFIG["client_id"], CONFIG["client_secret"]))
        s["refresh_token"] = None
        s["notice"] = "Refresh token revoked."
    return RedirectResponse("/", status_code=303)


@app.post("/logout")
def logout(request: Request):
    s = SESSIONS.pop(request.cookies.get(COOKIE, ""), None)
    if not s:
        return RedirectResponse("/", status_code=303)
    q = {"id_token_hint": s["id_token"], "post_logout_redirect_uri": f"{BASE_URL}/signed-out", "state": secrets.token_urlsafe(8)}
    resp = RedirectResponse(f"{ISSUER}/oauth/logout?{urlencode(q)}", status_code=303)
    resp.delete_cookie(COOKIE, path="/")
    return resp


@app.get("/signed-out", response_class=HTMLResponse)
def signed_out():
    return page("<p data-testid=signed-out-page>You have been signed out of this app and of Ifora.</p>"
                "<p><a class=b href='/'>Home</a></p>")
