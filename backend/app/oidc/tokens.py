"""Token endpoint logic: client authentication, authorization-code exchange, ID token and access token (ADR 005 §5).

Code handling (RFC 6749 §4.1.3/§10.5, RFC 7636, RFC 9700): the code is claimed with one atomic UPDATE so it can be
spent once; a second presentation is a replay and is audited. A code that fails any check after it was claimed is
burned (an attacker gets one guess per code). Refresh tokens arrive in M3, so no refresh token is issued yet.
"""

import base64
import hashlib
import hmac
import re
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple
from urllib.parse import unquote_plus

from sqlalchemy import update
from sqlalchemy.orm import Session

from backend.app.auth.authn import acr_for
from backend.app.config import settings
from backend.app.oidc import keys
from backend.app.oidc.authorize import _h, now
from backend.app.oidc.claims import user_claims
from backend.app.oidc.clients import authenticate_client
from backend.app.oidc.models import AuthorizationCode, OIDCClient
from backend.app.tenancy import Tenant
from backend.app.users.model import User

_VERIFIER = re.compile(r"^[A-Za-z0-9\-._~]{43,128}$")


class TokenError(Exception):
    def __init__(self, error: str, description: str, status: int = 400, www_authenticate: Optional[str] = None):
        self.error, self.description, self.status, self.www_authenticate = error, description, status, www_authenticate


def parse_basic(header: Optional[str]) -> Optional[Tuple[str, str]]:
    """RFC 6749 §2.3.1: id and secret are form-urlencoded, then joined with ':' and base64'd."""
    if not header or not header.lower().startswith("basic "):
        return None
    try:
        raw = base64.b64decode(header[6:].strip(), validate=True).decode()
        cid, secret = raw.split(":", 1)
    except Exception:
        raise TokenError("invalid_client", "malformed Basic credentials", 401, 'Basic realm="oauth"')
    return unquote_plus(cid), unquote_plus(secret)


def authenticate(db: Session, header: Optional[str], form: Dict[str, str]) -> OIDCClient:
    if "client_secret" in form:
        raise TokenError("invalid_request", "client_secret_post is not supported; use HTTP Basic authentication")
    basic = parse_basic(header)
    body_id = form.get("client_id")
    if basic:
        cid, secret = basic
        if body_id is not None and body_id != cid:
            raise TokenError("invalid_request", "client_id does not match the Authorization header")
        client = authenticate_client(db, cid, secret)
        if client is None:
            raise TokenError("invalid_client", "client authentication failed", 401, 'Basic realm="oauth"')
        return client
    if not body_id or len(body_id) > 64:
        raise TokenError("invalid_client", "client authentication required", 401, 'Basic realm="oauth"')
    client = db.query(OIDCClient).filter(OIDCClient.client_id == body_id).first()
    # Only public clients may authenticate by id alone (PKCE is what protects them).
    if client is None or client.status != "active" or client.client_type != "public":
        raise TokenError("invalid_client", "client authentication failed", 401, 'Basic realm="oauth"')
    return client


def _pkce_ok(verifier: str, challenge: str) -> bool:
    if not _VERIFIER.match(verifier):
        return False
    digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return hmac.compare_digest(digest, challenge)


def _at_hash(access_token: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(access_token.encode()).digest()[:16]).rstrip(b"=").decode()


def exchange_code(db: Session, client: OIDCClient, form: Dict[str, str], audit_replay) -> Tuple[Dict, User]:
    if form.get("grant_type") != "authorization_code":
        raise TokenError("unsupported_grant_type", "only authorization_code is supported")
    if "authorization_code" not in client.grant_types:
        raise TokenError("unauthorized_client", "this client may not use the authorization code grant")
    keys.signing_key(db)  # fail (503) before spending the code if signing is not configured; also settles key rotation
    code, verifier, redirect_uri = form.get("code"), form.get("code_verifier"), form.get("redirect_uri")
    if not code or not verifier or not redirect_uri or len(code) > 128:
        raise TokenError("invalid_request", "code, redirect_uri and code_verifier are required")

    row = db.query(AuthorizationCode).filter(AuthorizationCode.code_hash == _h(code)).first()
    if row is None or row.client_pk != client.id:
        raise TokenError("invalid_grant", "invalid or expired authorization code")  # another client's code is not burned

    spent = db.execute(
        update(AuthorizationCode).where(AuthorizationCode.id == row.id, AuthorizationCode.used_at.is_(None)).values(used_at=now())
    ).rowcount
    db.commit()  # the claim must be durable now: key lookups below may roll the transaction back
    if spent != 1:
        audit_replay(row)  # RFC 6749 §4.1.2: treat reuse as an attack signal (tokens from refresh families revoked in M3)
        db.commit()
        raise TokenError("invalid_grant", "invalid or expired authorization code")

    user = db.get(User, row.user_id)
    try:
        if row.expires_at <= now():
            raise TokenError("invalid_grant", "invalid or expired authorization code")
        if redirect_uri != row.redirect_uri:
            raise TokenError("invalid_grant", "redirect_uri does not match the authorization request")
        if not _pkce_ok(verifier, row.code_challenge):
            raise TokenError("invalid_grant", "PKCE verification failed")
        if user is None or user.status != "active" or client.status != "active":
            raise TokenError("invalid_grant", "invalid or expired authorization code")
    except TokenError:
        db.commit()  # the code stays burned
        raise

    return _issue(db, client, user, row), user


def _issue(db: Session, client: OIDCClient, user: User, row: AuthorizationCode) -> Dict:
    scopes = [s for s in row.scopes if s != "offline_access"]  # no refresh tokens until M3, so do not claim the scope
    t = int(datetime.now(timezone.utc).timestamp())
    tenant = db.get(Tenant, user.tenant_id)
    acr = acr_for(row.amr)
    auth_time = int(row.auth_time.timestamp())
    access = keys.sign_jwt(db, {
        "iss": settings.OIDC_ISSUER, "sub": user.public_id, "aud": settings.OIDC_ISSUER,  # no resource registry yet
        "client_id": client.client_id, "scope": " ".join(scopes), "iat": t, "exp": t + settings.OIDC_ACCESS_TOKEN_TTL_SECONDS,
        "jti": str(uuid.uuid4()), "auth_time": auth_time, "tenant": tenant.slug if tenant else None,
    }, typ="at+jwt")
    idc = {
        **user_claims(db, user, scopes),
        "iss": settings.OIDC_ISSUER, "aud": client.client_id, "iat": t, "exp": t + settings.OIDC_ID_TOKEN_TTL_SECONDS,
        "auth_time": auth_time, "amr": list(row.amr), "acr": acr, "at_hash": _at_hash(access),
    }
    if row.nonce:
        idc["nonce"] = row.nonce
    return {
        "access_token": access, "token_type": "Bearer", "expires_in": settings.OIDC_ACCESS_TOKEN_TTL_SECONDS,
        "id_token": keys.sign_jwt(db, idc), "scope": " ".join(scopes),
    }
