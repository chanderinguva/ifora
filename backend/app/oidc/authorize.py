"""Authorization endpoint logic (ADR 005 §3, RFC 6749 §4.1, RFC 7636, RFC 9700, RFC 9207).

Order of validation matters: until the client and redirect URI are proven genuine, errors are shown to the user and
NEVER redirected (an unvalidated redirect target would make this an open redirector). After that, errors go back to
the client's exact registered redirect URI.
"""

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import update
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.tenancy import issuer as tenant_issuer
from backend.app.oidc.clients import SUPPORTED_SCOPES
from backend.app.oidc.models import AuthorizationCode, OIDCClient, OIDCConsent, PendingAuthRequest

_PKCE = re.compile(r"^[A-Za-z0-9\-._~]{43,128}$")  # RFC 7636 §4.1/§4.2
MAX_PARAM = 512

SCOPE_DESCRIPTIONS = {
    "openid": "Confirm who you are",
    "profile": "Your name and profile details",
    "email": "Your email address",
    "groups": "The groups you belong to",
    "offline_access": "Stay signed in to this application when you are away",
}


def now() -> datetime:
    return datetime.now(timezone.utc)


def _h(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class AuthzError(Exception):
    """Error to redirect to the client (redirect URI already validated)."""

    def __init__(self, error: str, description: str):
        self.error, self.description = error, description


class ShownError(Exception):
    """Error to show to the user, never redirected (client or redirect URI not trustworthy)."""


@dataclass
class Params:
    client: OIDCClient
    redirect_uri: str
    scopes: List[str]
    state: Optional[str]
    nonce: Optional[str]
    code_challenge: str
    prompt: Optional[str]
    max_age: Optional[int] = None
    acr_values: Optional[List[str]] = None


def redirect_with(redirect_uri: str, params: Dict[str, Optional[str]]) -> str:
    """Append response parameters to the registered URI (keeping any query it already has). Always carries `iss`."""
    parts = urlsplit(redirect_uri)
    q = parse_qsl(parts.query, keep_blank_values=True)
    q += [(k, v) for k, v in {**params, "iss": tenant_issuer()}.items() if v is not None]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q), ""))


def validate_request(db: Session, q: Dict[str, str]) -> Params:
    """Validate raw query parameters. Raises ShownError before the redirect URI is trusted, AuthzError after."""
    client_id, redirect_uri = q.get("client_id"), q.get("redirect_uri")
    if not client_id or len(client_id) > 64:
        raise ShownError("Missing or invalid client_id")
    client = db.query(OIDCClient).filter(OIDCClient.client_id == client_id).first()
    if client is None or client.status != "active":
        raise ShownError("Unknown or disabled application")
    # Exact string match against the registered list; no normalisation, prefix, case-folding or wildcard.
    if not redirect_uri or redirect_uri not in client.redirect_uris:
        raise ShownError("The redirect URI is not registered for this application")

    state = q.get("state")
    if state is not None and len(state) > MAX_PARAM:
        raise AuthzError("invalid_request", "state is too long")
    if "request" in q or "request_uri" in q:
        raise AuthzError("request_not_supported", "request objects are not supported")
    if q.get("response_type") != "code":
        raise AuthzError("unsupported_response_type", "only response_type=code is supported")
    if "authorization_code" not in client.grant_types:
        raise AuthzError("unauthorized_client", "this client may not use the authorization code grant")

    challenge = q.get("code_challenge")
    if not challenge:
        raise AuthzError("invalid_request", "PKCE is required: send code_challenge")
    if q.get("code_challenge_method") != "S256":
        raise AuthzError("invalid_request", "code_challenge_method must be S256")
    if not _PKCE.match(challenge):
        raise AuthzError("invalid_request", "malformed code_challenge")

    scopes = [s for s in (q.get("scope") or "").split(" ") if s]
    if "openid" not in scopes:
        raise AuthzError("invalid_scope", "the openid scope is required")
    for s in scopes:
        if s not in SUPPORTED_SCOPES or s not in client.allowed_scopes:
            raise AuthzError("invalid_scope", f"scope not allowed for this client: {s[:40]}")
    scopes = [s for s in SUPPORTED_SCOPES if s in scopes]

    nonce = q.get("nonce")
    if nonce is not None and len(nonce) > MAX_PARAM:
        raise AuthzError("invalid_request", "nonce is too long")

    prompt = q.get("prompt")
    if prompt is not None:
        values = prompt.split(" ")
        if any(v not in ("none", "consent", "login", "select_account") for v in values) or len(set(values)) != len(values):
            raise AuthzError("invalid_request", "invalid prompt")
        if "none" in values and len(values) > 1:
            raise AuthzError("invalid_request", "prompt=none cannot be combined with other values")
    max_age = None
    if "max_age" in q:
        if not re.fullmatch(r"[0-9]{1,9}", q["max_age"]):
            raise AuthzError("invalid_request", "max_age must be a non-negative integer number of seconds")
        max_age = int(q["max_age"])
    acr = None
    if q.get("acr_values"):
        if len(q["acr_values"]) > MAX_PARAM:
            raise AuthzError("invalid_request", "acr_values is too long")
        acr = [v for v in q["acr_values"].split(" ") if v]

    return Params(client, redirect_uri, scopes, state, nonce, challenge, prompt, max_age, acr)


def needs_reauth(p: Params, session) -> bool:
    """Must the user authenticate again for this request? (OIDC Core 3.1.2.1 prompt=login, max_age, acr_values.)

    acr_values is a voluntary request: when the session is below the asked level the user is sent through sign-in once;
    whatever level they then reach is reported honestly in the ID token's `acr`."""
    wants = bool(p.prompt and "login" in p.prompt.split(" ")) or p.max_age is not None or bool(p.acr_values)
    if session is None:
        return wants  # a fresh sign-in is coming anyway; recorded so a stale session cannot be reused later
    if p.prompt and "login" in p.prompt.split(" "):
        return True
    if p.max_age is not None and (now() - session.auth_time).total_seconds() > p.max_age:
        return True
    if p.acr_values:
        from backend.app.auth.authn import acr_for

        return acr_for(session.amr) not in p.acr_values
    return False


def get_consent(db: Session, user_id: int, client: OIDCClient) -> Optional[OIDCConsent]:
    return db.query(OIDCConsent).filter(
        OIDCConsent.user_id == user_id, OIDCConsent.client_pk == client.id, OIDCConsent.revoked_at.is_(None)
    ).first()


def consent_required(db: Session, user_id: int, client: OIDCClient, scopes: List[str], prompt: Optional[str]) -> bool:
    """First-party clients skip the screen (an implicit consent row is recorded); everyone else needs a stored
    consent covering every requested scope, or prompt=consent forces the screen."""
    if prompt and "consent" in prompt.split(" "):
        return not client.first_party
    if client.first_party:
        return False
    c = get_consent(db, user_id, client)
    return c is None or not set(scopes) <= set(c.scopes)


def record_consent(db: Session, user_id: int, client: OIDCClient, scopes: List[str], via: str) -> None:
    c = db.query(OIDCConsent).filter(OIDCConsent.user_id == user_id, OIDCConsent.client_pk == client.id).first()
    if c is None:
        db.add(OIDCConsent(user_id=user_id, client_pk=client.id, scopes=scopes, granted_via=via))
        return
    if c.revoked_at is not None:
        c.scopes = list(scopes)  # a revoked consent starts over
    else:
        c.scopes = [s for s in SUPPORTED_SCOPES if s in set(c.scopes) | set(scopes)]
    c.granted_via, c.revoked_at, c.updated_at = via, None, now()


def park(db: Session, p: Params, auth_after: Optional[datetime] = None) -> str:
    raw = secrets.token_urlsafe(32)
    db.add(PendingAuthRequest(
        request_hash=_h(raw), client_pk=p.client.id, redirect_uri=p.redirect_uri, scopes=p.scopes, state=p.state,
        nonce=p.nonce, code_challenge=p.code_challenge, prompt=p.prompt, auth_after=auth_after,
        expires_at=now() + timedelta(seconds=settings.OIDC_PENDING_REQUEST_TTL_SECONDS),
    ))
    return raw


def claim_pending(db: Session, raw: str) -> Optional[PendingAuthRequest]:
    """Atomically take a pending request: only the first caller gets it, and only before it expires."""
    if not raw or len(raw) > 128:
        return None
    n = db.execute(
        update(PendingAuthRequest)
        .where(PendingAuthRequest.request_hash == _h(raw), PendingAuthRequest.decided_at.is_(None),
               PendingAuthRequest.expires_at > now())
        .values(decided_at=now())
    ).rowcount
    if n != 1:
        return None
    return db.query(PendingAuthRequest).filter(PendingAuthRequest.request_hash == _h(raw)).one()


def peek_pending(db: Session, raw: str) -> Optional[PendingAuthRequest]:
    if not raw or len(raw) > 128:
        return None
    r = db.query(PendingAuthRequest).filter(PendingAuthRequest.request_hash == _h(raw)).first()
    if r is None or r.decided_at is not None or r.expires_at <= now():
        return None
    return r


def mint_code(db: Session, *, client: OIDCClient, user_id: int, redirect_uri: str, scopes: List[str],
              nonce: Optional[str], code_challenge: str, auth_time: datetime, amr: List[str]) -> str:
    raw = secrets.token_urlsafe(32)
    db.add(AuthorizationCode(
        code_hash=_h(raw), client_pk=client.id, user_id=user_id, redirect_uri=redirect_uri, scopes=scopes,
        nonce=nonce, code_challenge=code_challenge, auth_time=auth_time, amr=list(amr),
        expires_at=now() + timedelta(seconds=settings.OIDC_CODE_TTL_SECONDS),
    ))
    return raw
