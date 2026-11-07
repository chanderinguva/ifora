"""RP-initiated logout (OpenID Connect RP-Initiated Logout 1.0).

A relying party may only send the user's browser back to a post-logout URI it registered (exact match), and may only
identify itself with an ID token WE signed (expired is fine) or its client_id. The user is always asked to confirm on
our own page, so a hostile site cannot silently sign people out. Refresh tokens (offline access) survive logout by
design; withdrawing access is the Connected applications page.
"""

import base64
import json
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.oidc import keys
from backend.app.oidc.models import OIDCClient

PARAMS = ("id_token_hint", "post_logout_redirect_uri", "state", "client_id")
MAX = 4096


@dataclass
class Plan:
    client: Optional[OIDCClient]
    sub: Optional[str]                 # subject proven by a valid ID token hint
    redirect_uri: Optional[str]        # only set when registered for the identified client
    state: Optional[str]


def _unverified_aud(token: str) -> Optional[str]:
    """Read `aud` only to know which client to check the signature against; it is trusted only after verification."""
    try:
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        aud = claims.get("aud")
        return aud if isinstance(aud, str) else (aud[0] if isinstance(aud, list) and aud and isinstance(aud[0], str) else None)
    except Exception:
        return None


def resolve(db: Session, p: dict) -> Plan:
    for k in PARAMS:
        if p.get(k) is not None and (not isinstance(p[k], str) or len(p[k]) > MAX):
            return Plan(None, None, None, None)
    client: Optional[OIDCClient] = None
    sub: Optional[str] = None
    hint = p.get("id_token_hint")
    if hint:
        aud = _unverified_aud(hint)
        candidate = db.query(OIDCClient).filter(OIDCClient.client_id == aud).first() if aud else None
        if candidate is not None and candidate.status == "active":
            try:
                claims = keys.verify_jwt(db, hint, issuer=settings.OIDC_ISSUER, audience=candidate.client_id, allow_expired=True)
                client, sub = candidate, claims.get("sub")
            except (keys.TokenError, keys.KeyConfigError):
                client = None
    cid = p.get("client_id")
    if cid:
        named = db.query(OIDCClient).filter(OIDCClient.client_id == cid).first()
        if named is None or named.status != "active" or (client is not None and named.id != client.id):
            return Plan(None, None, None, None)  # a client_id that contradicts the hint, or is unknown: no redirect
        client = client or named
    uri = p.get("post_logout_redirect_uri")
    redirect = uri if client is not None and uri and uri in (client.post_logout_redirect_uris or []) else None
    return Plan(client, sub, redirect, p.get("state") if redirect else None)


def redirect_url(plan: Plan) -> Optional[str]:
    if not plan.redirect_uri:
        return None
    parts = urlsplit(plan.redirect_uri)
    q = parse_qsl(parts.query, keep_blank_values=True)
    if plan.state:
        q.append(("state", plan.state))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q), ""))
