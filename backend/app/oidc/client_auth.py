"""private_key_jwt client authentication (RFC 7523 §3, OIDC Core §9).

The client signs a short-lived JWT with a key whose public half it registered; we hold no secret for it.
Checks: algorithm allow-list (RS256/ES256), signature against the client's own registered keys, iss == sub ==
client_id, aud is this issuer or the endpoint called, exp present and at most MAX_LIFETIME away, jti present and
never seen before (replay store in Redis; if the store is unavailable authentication FAILS: a replayable
assertion is worse than a refused one). Every failure is the same opaque invalid_client.
"""

import base64
import hashlib
import json
import time
from typing import Dict, Optional

import redis
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet
from joserfc.jwt import JWTClaimsRegistry
from sqlalchemy.orm import Session

from backend.app import ratelimit
from backend.app.config import settings
from backend.app.oidc.models import OIDCClient

ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
ALGS = ["RS256", "ES256"]
MAX_LIFETIME = 300
MAX_LEN = 4096


def _unverified_iss(assertion: str) -> Optional[str]:
    try:
        payload = assertion.split(".")[1]
        iss = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))).get("iss")
        return iss if isinstance(iss, str) and len(iss) <= 64 else None
    except Exception:
        return None


def _remember_jti(client_id: str, jti: str, ttl: int) -> bool:
    key = f"cja:{client_id}:{hashlib.sha256(jti.encode()).hexdigest()}"
    try:
        return bool(ratelimit._redis().set(key, "1", nx=True, ex=max(ttl, 1)))
    except redis.RedisError:
        return False  # fail closed


def authenticate_assertion(db: Session, form: Dict[str, str], endpoint: str) -> Optional[OIDCClient]:
    """Return the authenticated client, or None. The caller turns None into invalid_client."""
    assertion = form.get("client_assertion")
    if form.get("client_assertion_type") != ASSERTION_TYPE or not assertion or len(assertion) > MAX_LEN:
        return None
    cid = _unverified_iss(assertion)
    if cid is None or (form.get("client_id") not in (None, cid)):
        return None
    client = db.query(OIDCClient).filter(OIDCClient.client_id == cid).first()
    if (client is None or client.status != "active" or client.client_type not in ("confidential", "service")
            or client.token_endpoint_auth_method != "private_key_jwt" or not client.jwks):
        return None
    iss = settings.OIDC_ISSUER
    auds = list({iss, iss.rstrip("/"), f"{iss.rstrip('/')}/oauth/{endpoint}"})
    try:
        decoded = jwt.decode(assertion, KeySet.import_key_set(client.jwks), algorithms=ALGS)
        JWTClaimsRegistry(
            leeway=settings.OIDC_CLOCK_SKEW_SECONDS,
            iss={"essential": True, "value": cid}, sub={"essential": True, "value": cid},
            aud={"essential": True, "values": auds}, exp={"essential": True}, jti={"essential": True},
        ).validate(decoded.claims)
        c = decoded.claims
        now = int(time.time())
        if not isinstance(c["jti"], str) or not c["jti"] or len(c["jti"]) > 256:
            return None
        if int(c["exp"]) > now + MAX_LIFETIME + settings.OIDC_CLOCK_SKEW_SECONDS:
            return None  # long-lived assertions defeat the replay window
        ttl = int(c["exp"]) - now + settings.OIDC_CLOCK_SKEW_SECONDS
    except (JoseError, ValueError, KeyError, TypeError):
        return None
    return client if _remember_jti(cid, c["jti"], ttl) else None
