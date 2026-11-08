"""Client registry rules (ADR 005 §7): validation of what a client may be, secrets, client authentication.

Validation follows RFC 9700: redirect URIs are matched by exact string comparison later, so they must be
unambiguous when registered (absolute, no wildcard, no fragment, https except loopback). PKCE is not an option
on a client: the authorize endpoint will always require it.
"""

import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from passlib.hash import argon2
from sqlalchemy.orm import Session

from backend.app.oidc.models import OIDCClient, OIDCClientSecret

SUPPORTED_SCOPES = ("openid", "profile", "email", "groups", "offline_access")
CLIENT_TYPES = ("public", "confidential", "service")
USER_SCOPES = SUPPORTED_SCOPES  # identity scopes: never granted to a service client (there is no user)
_SERVICE_SCOPE = re.compile(r"^[a-z][a-z0-9:._-]{0,63}$")
MAX_SERVICE_SCOPES = 20
MAX_URIS = 10
AUTH_METHODS = ("client_secret_basic", "private_key_jwt")
MAX_JWKS_KEYS = 5
_PRIVATE_MEMBERS = {"d", "p", "q", "dp", "dq", "qi", "oth", "k"}
_PUBLIC_MEMBERS = {"kty", "kid", "use", "alg", "n", "e", "crv", "x", "y"}
MAX_ACTIVE_SECRETS = 2
SECRET_PREFIX = "idf_cs_"
_LOOPBACK = {"localhost", "127.0.0.1", "::1"}
_DUMMY_HASH = argon2.hash("dummy-client-secret-for-timing-equalisation")


class ClientError(ValueError):
    """Invalid client configuration; the message is safe to show an administrator."""


def new_client_id() -> str:
    return "idf_" + secrets.token_urlsafe(18)


def new_secret() -> str:
    return SECRET_PREFIX + secrets.token_urlsafe(32)


def validate_redirect_uri(uri: str, what: str = "redirect URI") -> str:
    """Absolute, exact, https (or http on loopback), no wildcards/fragments/userinfo."""
    if not isinstance(uri, str) or not uri or len(uri) > 2000 or uri != uri.strip():
        raise ClientError(f"invalid {what}")
    if "*" in uri:
        raise ClientError(f"{what} must not contain wildcards: {uri}")
    parts = urlsplit(uri)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ClientError(f"{what} must be an absolute http(s) URL: {uri}")
    if parts.fragment or "#" in uri:
        raise ClientError(f"{what} must not contain a fragment: {uri}")
    if parts.username or parts.password:
        raise ClientError(f"{what} must not contain credentials: {uri}")
    if parts.scheme == "http" and parts.hostname not in _LOOPBACK:
        raise ClientError(f"{what} must use https (http is only allowed for localhost): {uri}")
    return uri


def validate_uri_list(uris: List[str], what: str, *, required: bool) -> List[str]:
    if required and not uris:
        raise ClientError(f"at least one {what} is required")
    if len(uris) > MAX_URIS:
        raise ClientError(f"at most {MAX_URIS} {what}s")
    out = [validate_redirect_uri(u, what) for u in uris]
    if len(set(out)) != len(out):
        raise ClientError(f"duplicate {what}")
    return out


def validate_scopes(scopes: List[str]) -> List[str]:
    unknown = [s for s in scopes if s not in SUPPORTED_SCOPES]
    if unknown:
        raise ClientError(f"unsupported scope: {unknown[0]}")
    if "openid" not in scopes:
        raise ClientError("the openid scope is required")
    return [s for s in SUPPORTED_SCOPES if s in scopes]  # canonical order, de-duplicated


def validate_service_scopes(scopes: List[str]) -> List[str]:
    """Service clients act as themselves: scopes are application-defined permissions, not identity claims."""
    if not scopes:
        raise ClientError("at least one scope is required")
    if len(scopes) > MAX_SERVICE_SCOPES:
        raise ClientError(f"at most {MAX_SERVICE_SCOPES} scopes")
    for sc in scopes:
        if not isinstance(sc, str) or not _SERVICE_SCOPE.match(sc):
            raise ClientError(f"invalid scope {sc!r}: lowercase letters, digits and : . _ - only, at most 64 characters")
        if sc in USER_SCOPES:
            raise ClientError(f"{sc} is an identity scope and cannot be granted to a service client")
    if len(set(scopes)) != len(scopes):
        raise ClientError("duplicate scope")
    return list(scopes)


def validate_audiences(audiences: List[str]) -> List[str]:
    """Resource identifiers (RFC 8707): absolute https (or loopback http) URIs without fragment or wildcard."""
    if not audiences:
        raise ClientError("at least one audience (resource identifier) is required")
    if len(audiences) > MAX_URIS:
        raise ClientError(f"at most {MAX_URIS} audiences")
    out = [validate_redirect_uri(a, "audience") for a in audiences]
    if len(set(out)) != len(out):
        raise ClientError("duplicate audience")
    return out


def validate_jwks(jwks: Any) -> Dict[str, Any]:
    """Inline public keys for private_key_jwt. Refuses private key material outright (a pasted private key must never be
    stored), weak RSA, curves other than P-256, duplicate or missing `kid`. Returns only the public members."""
    from joserfc.jwk import ECKey, RSAKey

    if not isinstance(jwks, dict) or not isinstance(jwks.get("keys"), list) or not jwks["keys"]:
        raise ClientError("jwks must be a JSON object with a non-empty keys array")
    if len(jwks["keys"]) > MAX_JWKS_KEYS:
        raise ClientError(f"at most {MAX_JWKS_KEYS} keys")
    out, kids = [], set()
    for k in jwks["keys"]:
        if not isinstance(k, dict):
            raise ClientError("each key must be an object")
        if _PRIVATE_MEMBERS & set(k):
            raise ClientError("jwks must contain public keys only; remove private key material")
        kid = k.get("kid")
        if not isinstance(kid, str) or not kid or len(kid) > 64:
            raise ClientError("every key needs a kid (at most 64 characters)")
        if kid in kids:
            raise ClientError(f"duplicate kid {kid}")
        kids.add(kid)
        if k.get("use") not in (None, "sig"):
            raise ClientError("keys must be for signatures (use=sig)")
        kty, alg = k.get("kty"), k.get("alg")
        if kty == "RSA":
            if alg not in (None, "RS256"):
                raise ClientError(f"key {kid}: RSA keys sign with RS256")
            try:
                key = RSAKey.import_key({m: k[m] for m in ("kty", "n", "e")})
            except Exception:
                raise ClientError(f"key {kid} is not a valid RSA public key")
            if key.as_dict(private=False).get("n") and (int.from_bytes(_b64u(k["n"]), "big").bit_length() < 2048):
                raise ClientError(f"key {kid}: RSA keys must be at least 2048 bits")
        elif kty == "EC":
            if alg not in (None, "ES256") or k.get("crv") != "P-256":
                raise ClientError(f"key {kid}: only P-256 / ES256 elliptic-curve keys are supported")
            try:
                ECKey.import_key({m: k[m] for m in ("kty", "crv", "x", "y")})
            except Exception:
                raise ClientError(f"key {kid} is not a valid EC public key")
        else:
            raise ClientError(f"key {kid}: unsupported key type (RSA or EC)")
        out.append({m: v for m, v in k.items() if m in _PUBLIC_MEMBERS})
    return {"keys": out}


def _b64u(v: str) -> bytes:
    import base64

    return base64.urlsafe_b64decode(v + "=" * (-len(v) % 4))


def grant_types_for(scopes: List[str]) -> List[str]:
    # authorization_code always; refresh_token only if the client may ask for offline_access.
    # client_credentials, implicit and password grants are deliberately not offered here.
    return ["authorization_code", "refresh_token"] if "offline_access" in scopes else ["authorization_code"]


def client_to_dict(c: OIDCClient, secrets_: Optional[List[OIDCClientSecret]] = None) -> Dict[str, Any]:
    d = {
        "id": c.id,
        "application_id": c.application_id,
        "client_id": c.client_id,
        "name": c.name,
        "description": c.description,
        "client_type": c.client_type,
        "token_endpoint_auth_method": c.token_endpoint_auth_method,
        "first_party": c.first_party,
        "status": c.status,
        "redirect_uris": c.redirect_uris,
        "post_logout_redirect_uris": c.post_logout_redirect_uris,
        "allowed_scopes": c.allowed_scopes,
        "allowed_audiences": c.allowed_audiences or [],
        "jwks": c.jwks,
        "access_token_format": c.access_token_format,
        "grant_types": c.grant_types,
        "created_at": c.created_at.isoformat(),
        "updated_at": c.updated_at.isoformat(),
    }
    if secrets_ is not None:
        d["secrets"] = [secret_to_dict(s) for s in secrets_]
    return d


def secret_to_dict(s: OIDCClientSecret) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    state = "revoked" if s.revoked_at else "expired" if s.expires_at and s.expires_at <= now else "active"
    return {
        "id": s.id,
        "hint": s.hint,
        "state": state,
        "created_at": s.created_at.isoformat(),
        "expires_at": s.expires_at.isoformat() if s.expires_at else None,
        "last_used_at": s.last_used_at.isoformat() if s.last_used_at else None,
    }


def active_secrets(db: Session, client: OIDCClient) -> List[OIDCClientSecret]:
    now = datetime.now(timezone.utc)
    rows = db.query(OIDCClientSecret).filter(
        OIDCClientSecret.client_pk == client.id, OIDCClientSecret.revoked_at.is_(None)
    ).all()
    return [s for s in rows if s.expires_at is None or s.expires_at > now]


def add_secret(db: Session, client: OIDCClient, expires_in_days: Optional[int] = None) -> str:
    """Create a secret and return it in clear ONCE; only its Argon2id hash is stored."""
    if client.client_type not in ("confidential", "service"):
        raise ClientError("only confidential and service clients have secrets")
    if client.token_endpoint_auth_method != "client_secret_basic":
        raise ClientError("this client authenticates with a signed assertion (private_key_jwt), not a secret")
    if len(active_secrets(db, client)) >= MAX_ACTIVE_SECRETS:
        raise ClientError(f"at most {MAX_ACTIVE_SECRETS} active secrets; revoke an old one first")
    raw = new_secret()
    db.add(OIDCClientSecret(
        client_pk=client.id,
        secret_hash=argon2.hash(raw),
        hint=raw[-4:],
        expires_at=datetime.now(timezone.utc) + timedelta(days=expires_in_days) if expires_in_days else None,
    ))
    return raw


def authenticate_client(db: Session, client_id: str, presented_secret: Optional[str]) -> Optional[OIDCClient]:
    """Confidential-client authentication for the token endpoint. Returns the client or None; never says why.

    Unknown / disabled clients still burn an Argon2 verification so timing does not reveal which client_ids exist.
    """
    client = db.query(OIDCClient).filter(OIDCClient.client_id == client_id).first()
    ok = False
    if client is not None and client.status == "active" and client.client_type in ("confidential", "service") and client.token_endpoint_auth_method == "client_secret_basic" and presented_secret:
        for s in active_secrets(db, client):
            try:
                if argon2.verify(presented_secret, s.secret_hash):
                    s.last_used_at = datetime.now(timezone.utc)
                    ok = True
                    break
            except Exception:
                continue
    else:
        try:
            argon2.verify(presented_secret or "", _DUMMY_HASH)
        except Exception:
            pass
    return client if ok else None
