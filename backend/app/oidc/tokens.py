"""Token endpoint logic: client authentication, authorization-code exchange, ID token and access token (ADR 005 §5).

Code handling (RFC 6749 §4.1.3/§10.5, RFC 7636, RFC 9700): the code is claimed with one atomic UPDATE so it can be
spent once; a second presentation is a replay and is audited. A code that fails any check after it was claimed is
burned (an attacker gets one guess per code). Refresh tokens arrive in M3, so no refresh token is issued yet.
"""

import base64
import hashlib
import hmac
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
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
from backend.app.oidc.models import AccessToken, AuthorizationCode, OIDCClient
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


def authenticate(db: Session, header: Optional[str], form: Dict[str, str], endpoint: str = "token") -> OIDCClient:
    if "client_secret" in form:
        raise TokenError("invalid_request", "client_secret_post is not supported; use HTTP Basic authentication")
    if form.get("client_assertion") is not None or form.get("client_assertion_type") is not None:
        from backend.app.oidc import client_auth

        if header:
            raise TokenError("invalid_request", "use one client authentication method")
        client = client_auth.authenticate_assertion(db, form, endpoint)
        if client is None:
            raise TokenError("invalid_client", "client authentication failed", 401)
        return client
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


def exchange_code(db: Session, client: OIDCClient, form: Dict[str, str], audit) -> Tuple[Dict, User]:
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
        from backend.app.oidc import refresh

        revoked = refresh.revoke_for_code(db, row.id)  # RFC 6749 §4.1.2: tokens already issued from this code die with it
        audit("OIDC_CODE_REPLAY_DETECTED", row.user_id, {"client_id": client.client_id, "refresh_families_revoked": revoked})
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

    body = build_tokens(db, client, user, scopes=row.scopes, auth_time=row.auth_time, amr=row.amr, nonce=row.nonce)
    if "offline_access" in row.scopes and "refresh_token" in client.grant_types:
        from backend.app.oidc import refresh

        body["refresh_token"] = refresh.issue_family(db, client, user, row, row.scopes)
    return body, user


OPAQUE_PREFIX = "idf_at_"


def _store_opaque(db: Session, client: OIDCClient, raw: str, *, sub, user_id, aud, scopes, auth_time) -> None:
    db.add(AccessToken(token_hash=_h(raw), client_pk=client.id, user_id=user_id, sub=sub, audience=aud, scopes=list(scopes), auth_time=auth_time,
                       expires_at=datetime.now(timezone.utc) + timedelta(seconds=settings.OIDC_ACCESS_TOKEN_TTL_SECONDS)))
    db.flush()


def mint_access(db: Session, client: OIDCClient, *, sub: str, user_id: Optional[int], aud: str, scopes, auth_time, claims: Dict,
                defer: bool = False):
    """A JWT, or for clients registered with access_token_format = "opaque" a random reference token (hash stored).
    With defer=True an opaque token is returned with a `store()` callback instead of being persisted yet (signing the ID
    token can commit/rollback, so the row is written after it)."""
    if client.access_token_format == "opaque":
        raw = OPAQUE_PREFIX + secrets.token_urlsafe(32)
        store = lambda: _store_opaque(db, client, raw, sub=sub, user_id=user_id, aud=aud, scopes=scopes, auth_time=auth_time)  # noqa: E731
        if defer:
            return raw, store
        store()
        return raw
    ts = int(datetime.now(timezone.utc).timestamp())
    jwt_ = keys.sign_jwt(db, {
        "iss": settings.OIDC_ISSUER, "sub": sub, "aud": aud, "client_id": client.client_id, "scope": " ".join(scopes),
        "iat": ts, "exp": ts + settings.OIDC_ACCESS_TOKEN_TTL_SECONDS, "jti": str(uuid.uuid4()), **claims,
    }, typ="at+jwt")
    return (jwt_, lambda: None) if defer else jwt_


def build_tokens(db: Session, client: OIDCClient, user: User, *, scopes, auth_time, amr, nonce: Optional[str]) -> Dict:
    t = int(datetime.now(timezone.utc).timestamp())
    tenant = db.get(Tenant, user.tenant_id)
    auth_ts = int(auth_time.timestamp())
    access, store_access = mint_access(db, client, sub=user.public_id, user_id=user.id, aud=settings.OIDC_ISSUER,  # no resource registry yet
                                       scopes=scopes, auth_time=auth_time, claims={"auth_time": auth_ts, "tenant": tenant.slug if tenant else None},
                                       defer=True)
    idc = {
        **user_claims(db, user, list(scopes)),
        "iss": settings.OIDC_ISSUER, "aud": client.client_id, "iat": t, "exp": t + settings.OIDC_ID_TOKEN_TTL_SECONDS,
        "auth_time": auth_ts, "amr": list(amr), "acr": acr_for(list(amr)), "at_hash": _at_hash(access),
    }
    if nonce:
        idc["nonce"] = nonce
    id_token = keys.sign_jwt(db, idc)
    store_access()  # after signing: key handling may commit or roll back the transaction
    return {
        "access_token": access, "token_type": "Bearer", "expires_in": settings.OIDC_ACCESS_TOKEN_TTL_SECONDS,
        "id_token": id_token, "scope": " ".join(scopes),
    }


def client_credentials(db: Session, client: OIDCClient, form: Dict[str, str]) -> Dict:
    """RFC 6749 §4.4. The client acts as itself: no user, no ID token, no refresh token (§4.4.3).
    `scope` must be within the client's allow-list (default: all of it); `resource` (RFC 8707) must be one of its
    allowed audiences (default: the only one). The access token's `sub` is the client_id."""
    if "client_credentials" not in client.grant_types:
        raise TokenError("unauthorized_client", "this client may not use the client credentials grant")
    allowed = list(client.allowed_scopes)
    asked = form.get("scope")
    if asked is None or not asked.strip():
        scopes = allowed
    else:
        scopes = asked.split()
        if len(scopes) != len(set(scopes)) or any(sc not in allowed for sc in scopes):
            raise TokenError("invalid_scope", "scope is not allowed for this client")
    audiences = list(client.allowed_audiences or [])
    resource = form.get("resource")
    if resource is None:
        if len(audiences) != 1:
            raise TokenError("invalid_target", "resource is required for this client")
        resource = audiences[0]
    elif resource not in audiences:
        raise TokenError("invalid_target", "resource is not allowed for this client")
    tenant = db.get(Tenant, client.tenant_id)
    access = mint_access(db, client, sub=client.client_id, user_id=None, aud=resource, scopes=scopes, auth_time=None,
                         claims={"tenant": tenant.slug if tenant else None})
    return {"access_token": access, "token_type": "Bearer", "expires_in": settings.OIDC_ACCESS_TOKEN_TTL_SECONDS, "scope": " ".join(scopes)}
