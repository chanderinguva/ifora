"""RFC 7662 token introspection (ADR 005 P2.2).

Who may ask: a confidential or service client that authenticated with its secret. What it may learn:
- about a token issued TO it (any type it holds), or
- about an access token whose audience is one of the caller's own `allowed_audiences` (a resource server is
  registered as a client whose audiences include its own identifier).
Everything else, and every invalid/expired/revoked token, answers exactly {"active": false}: no oracle.

Unlike local JWT validation this sees state changes before `exp`: a disabled user or client, or consent the user
withdrew, makes an access token inactive immediately. Refresh tokens are active until used, revoked or expired.
"""

from typing import Dict

from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.oidc import keys, refresh
from backend.app.oidc.authorize import get_consent, now
from backend.app.oidc.models import OIDCClient, RefreshToken
from backend.app.users.model import User

INACTIVE: Dict = {"active": False}


def _refresh(db: Session, caller: OIDCClient, raw: str) -> Dict:
    row = db.query(RefreshToken).filter(RefreshToken.token_hash == refresh._h(raw)).first()
    if row is None or row.client_pk != caller.id:
        return INACTIVE
    t = now()
    if row.revoked_at or row.used_at or row.expires_at <= t or row.absolute_expires_at <= t:
        return INACTIVE
    user = db.get(User, row.user_id)
    if user is None or user.status != "active":
        return INACTIVE
    return {"active": True, "scope": " ".join(row.scopes), "client_id": caller.client_id, "token_type": "refresh_token",
            "sub": user.public_id, "iss": settings.OIDC_ISSUER, "iat": int(row.created_at.timestamp()), "exp": int(row.expires_at.timestamp())}


def _access(db: Session, caller: OIDCClient, raw: str) -> Dict:
    try:
        c = keys.verify_jwt(db, raw, issuer=settings.OIDC_ISSUER, audience=None, typ="at+jwt")
    except keys.TokenError:
        return INACTIVE
    aud = c.get("aud")
    auds = aud if isinstance(aud, list) else [aud]
    if c.get("client_id") != caller.client_id and not (set(auds) & set(caller.allowed_audiences or [])):
        return INACTIVE
    issued_to = db.query(OIDCClient).filter(OIDCClient.client_id == c.get("client_id")).first()
    if issued_to is None or issued_to.status != "active":
        return INACTIVE
    if issued_to.client_type != "service":  # a user token: the user must still exist and, unless first-party, still consent
        user = db.query(User).filter(User.public_id == c.get("sub")).first()
        if user is None or user.status != "active":
            return INACTIVE
        if not issued_to.first_party and get_consent(db, user.id, issued_to) is None:
            return INACTIVE
    out = {"active": True, "token_type": "Bearer"}
    for k in ("scope", "client_id", "sub", "aud", "iss", "iat", "exp", "jti"):
        if k in c:
            out[k] = c[k]
    return out


def introspect(db: Session, caller: OIDCClient, raw: str, hint: str | None) -> Dict:
    looks_jwt = raw.count(".") == 2
    if hint == "refresh_token" and not looks_jwt:
        return _refresh(db, caller, raw)
    if looks_jwt:
        return _access(db, caller, raw)
    return _refresh(db, caller, raw)
