"""CORS for the OIDC endpoints browsers call directly. Never credentialed: no cookies are involved, so
`Access-Control-Allow-Credentials` is never sent and a wildcard is safe where the data is public or bearer-protected.

- jwks, discovery: public, `*`.
- userinfo: bearer token in the Authorization header, `*` (a stolen token works from anywhere regardless of CORS).
- token: only for PUBLIC clients (browser apps with PKCE), and only from an origin that is one of that client's
  registered redirect URIs. Confidential clients never call the token endpoint from a browser.
"""

from typing import Optional
from urllib.parse import urlsplit

from fastapi import Request
from sqlalchemy.orm import Session

from backend.app.oidc.models import OIDCClient

MAX_AGE = "600"


def origin_of(uri: str) -> Optional[str]:
    p = urlsplit(uri)
    if p.scheme not in ("http", "https") or not p.netloc:
        return None
    return f"{p.scheme}://{p.netloc}"


def token_origin_allowed(db: Session, origin: Optional[str], client_id: Optional[str]) -> bool:
    if not origin or not client_id or len(client_id) > 64:
        return False
    c = db.query(OIDCClient).filter(OIDCClient.client_id == client_id).first()
    if c is None or c.status != "active" or c.client_type != "public":
        return False
    return origin in {origin_of(u) for u in c.redirect_uris}


def token_headers(db: Session, request: Request, client_id: Optional[str]) -> dict:
    origin = request.headers.get("origin")
    if token_origin_allowed(db, origin, client_id):
        return {"Access-Control-Allow-Origin": origin, "Vary": "Origin"}
    return {"Vary": "Origin"}


def preflight_token(db: Session, request: Request) -> dict:
    """The preflight carries no body, so the client is not known yet: allow when the origin belongs to ANY active
    public client; the real request is then re-checked against its own client."""
    origin = request.headers.get("origin")
    ok = False
    if origin:
        for c in db.query(OIDCClient).filter(OIDCClient.status == "active", OIDCClient.client_type == "public").all():
            if origin in {origin_of(u) for u in c.redirect_uris}:
                ok = True
                break
    h = {"Vary": "Origin"}
    if ok:
        h.update({"Access-Control-Allow-Origin": origin, "Access-Control-Allow-Methods": "POST",
                  "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Max-Age": MAX_AGE})
    return h


USERINFO = {"Access-Control-Allow-Origin": "*", "Access-Control-Expose-Headers": "WWW-Authenticate"}
USERINFO_PREFLIGHT = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, POST",
                      "Access-Control-Allow-Headers": "Authorization, Content-Type", "Access-Control-Max-Age": MAX_AGE}
