"""/oauth/token, /oauth/userinfo and discovery. No CORS headers are added here: browser-based public clients on
other origins are not supported yet (a non-credentialed policy for these endpoints is a later change)."""

from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.app import ratelimit
from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.config import settings
from backend.app.db import get_db
from backend.app.oidc import keys, refresh, tokens
from backend.app.oidc.claims import user_claims
from backend.app.oidc.clients import SUPPORTED_SCOPES
from backend.app.oidc.models import OIDCClient
from backend.app.users.model import User

router = APIRouter(tags=["oidc"])
NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
FORM = "application/x-www-form-urlencoded"


def _error(e: tokens.TokenError) -> JSONResponse:
    headers = dict(NO_STORE)
    if e.www_authenticate:
        headers["WWW-Authenticate"] = e.www_authenticate
    return JSONResponse({"error": e.error, "error_description": e.description}, status_code=e.status, headers=headers)


@router.post("/oauth/token")
async def token(request: Request, db: Session = Depends(get_db)):
    ident = ratelimit.client_ip(request)
    ratelimit.check("oauth_token", ident, settings.RATE_LIMIT_TOKEN_FAILURES)  # failures only are counted below
    try:
        if not (request.headers.get("content-type") or "").lower().startswith(FORM):
            raise tokens.TokenError("invalid_request", f"Content-Type must be {FORM}")
        pairs = (await request.form()).multi_items()
        form = dict(pairs)
        if len(pairs) != len(form):
            raise tokens.TokenError("invalid_request", "repeated parameter")
        client = tokens.authenticate(db, request.headers.get("authorization"), form)

        def audit(action: str, user_id: Optional[int], meta: dict):
            record(db, AuditAction(action), request, None, user_id, "user", {"client_id": client.client_id, **meta})

        grant = form.get("grant_type")
        if grant == "refresh_token":
            body, user = refresh.rotate(db, client, form, audit)
        else:
            body, user = tokens.exchange_code(db, client, form, audit)
        record(db, AuditAction.OIDC_TOKEN_ISSUED, request, user, user.id, "user",
               {"client_id": client.client_id, "scope": body["scope"], "grant": grant})
        db.commit()
    except tokens.TokenError as e:
        db.rollback()  # exchange_code already committed anything that must persist (a burned or replayed code)
        if e.error in ("invalid_client", "invalid_grant"):
            ratelimit.hit("oauth_token", ident, settings.RATE_LIMIT_TOKEN_WINDOW_SECONDS)
        return _error(e)
    except keys.KeyConfigError:
        db.rollback()  # nothing was spent: the code is still usable once signing is configured
        return JSONResponse({"error": "server_error", "error_description": "signing is not configured"}, 503, headers=NO_STORE)
    return JSONResponse(body, headers=NO_STORE)


def _bearer_error(error: Optional[str], desc: str = "", status: int = 401) -> JSONResponse:
    h = 'Bearer realm="oauth"' + (f', error="{error}", error_description="{desc}"' if error else "")
    return JSONResponse({"error": error or "invalid_request", "error_description": desc}, status, headers={**NO_STORE, "WWW-Authenticate": h})


@router.api_route("/oauth/userinfo", methods=["GET", "POST"])
def userinfo(request: Request, db: Session = Depends(get_db)):
    auth = request.headers.get("authorization") or ""
    if not auth.lower().startswith("bearer ") or not auth[7:].strip():
        return _bearer_error(None, "a Bearer access token is required")  # header only: never a query parameter
    try:
        claims = keys.verify_jwt(db, auth[7:].strip(), issuer=settings.OIDC_ISSUER, audience=settings.OIDC_ISSUER, typ="at+jwt")
    except keys.TokenError:
        return _bearer_error("invalid_token", "the access token is invalid or expired")
    except keys.KeyConfigError:
        return JSONResponse({"error": "server_error"}, 503, headers=NO_STORE)
    scopes = str(claims.get("scope", "")).split(" ")
    if "openid" not in scopes:
        return _bearer_error("insufficient_scope", "the openid scope is required", 403)
    user = db.query(User).filter(User.public_id == claims.get("sub")).first()
    client = db.query(OIDCClient).filter(OIDCClient.client_id == claims.get("client_id")).first()
    if user is None or user.status != "active" or client is None or client.status != "active":
        return _bearer_error("invalid_token", "the access token is invalid or expired")
    return JSONResponse(user_claims(db, user, scopes), headers=NO_STORE)


@router.get("/.well-known/openid-configuration")
def discovery():
    iss = settings.OIDC_ISSUER.rstrip("/")
    return JSONResponse({
        "issuer": settings.OIDC_ISSUER,
        "authorization_endpoint": f"{iss}/oauth/authorize",
        "token_endpoint": f"{iss}/oauth/token",
        "userinfo_endpoint": f"{iss}/oauth/userinfo",
        "jwks_uri": f"{iss}/oauth/jwks",
        "response_types_supported": ["code"],
        "response_modes_supported": ["query"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
        "scopes_supported": list(SUPPORTED_SCOPES),
        "token_endpoint_auth_methods_supported": ["client_secret_basic", "none"],
        "code_challenge_methods_supported": ["S256"],
        "claims_supported": ["sub", "iss", "aud", "exp", "iat", "auth_time", "nonce", "amr", "acr", "at_hash", "name", "given_name",
                             "family_name", "preferred_username", "zoneinfo", "locale", "updated_at", "email", "groups"],
        "authorization_response_iss_parameter_supported": True,
        "request_parameter_supported": False,
        "request_uri_parameter_supported": False,
    }, headers={"Cache-Control": "public, max-age=300", "Access-Control-Allow-Origin": "*"})


@router.post("/oauth/revoke")
async def revoke(request: Request, db: Session = Depends(get_db)):
    """RFC 7009. Revoking a refresh token ends its whole family. Access tokens are short-lived self-contained JWTs
    and cannot be recalled, which the response says honestly instead of pretending."""
    ident = ratelimit.client_ip(request)
    ratelimit.check("oauth_token", ident, settings.RATE_LIMIT_TOKEN_FAILURES)
    try:
        if not (request.headers.get("content-type") or "").lower().startswith(FORM):
            raise tokens.TokenError("invalid_request", f"Content-Type must be {FORM}")
        pairs = (await request.form()).multi_items()
        form = dict(pairs)
        if len(pairs) != len(form):
            raise tokens.TokenError("invalid_request", "repeated parameter")
        client = tokens.authenticate(db, request.headers.get("authorization"), form)
        raw = form.get("token")
        if not raw or len(raw) > 4096:
            raise tokens.TokenError("invalid_request", "token is required")
        if form.get("token_type_hint") == "access_token" or raw.count(".") == 2:
            raise tokens.TokenError("unsupported_token_type", "access tokens are short-lived and cannot be revoked; revoke the refresh token")
        row = db.query(refresh.RefreshToken).filter(refresh.RefreshToken.token_hash == refresh._h(raw)).first()
        if row is not None and row.client_pk == client.id:  # someone else's token: succeed silently, change nothing
            n = refresh.revoke_family(db, row.family_id)
            if n:
                record(db, AuditAction.OIDC_TOKEN_REVOKED, request, None, row.user_id, "user", {"client_id": client.client_id, "family": row.family_id})
        db.commit()
    except tokens.TokenError as e:
        db.rollback()
        if e.error == "invalid_client":
            ratelimit.hit("oauth_token", ident, settings.RATE_LIMIT_TOKEN_WINDOW_SECONDS)
        return _error(e)
    return JSONResponse({}, headers=NO_STORE)
