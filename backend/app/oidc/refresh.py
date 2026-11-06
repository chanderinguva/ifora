"""Refresh tokens: issue, rotate with reuse detection, revoke (RFC 6749 §6, RFC 7009, RFC 9700 §4.14).

Every use spends the token and returns a new one in the same family. A spent token that shows up again has been
copied by someone, and we cannot tell which holder is the thief, so the whole family dies and the user signs in again.
"""

import secrets
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Tuple

from sqlalchemy import update
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.oidc import tokens
from backend.app.oidc.authorize import _h, get_consent, now
from backend.app.oidc.models import AuthorizationCode, OIDCClient, RefreshToken  # noqa: F401 (RefreshToken re-exported)
from backend.app.users.model import User

PREFIX = "idf_rt_"
Audit = Callable[[str, Optional[int], dict], None]


def _new_raw() -> str:
    return PREFIX + secrets.token_urlsafe(32)


def issue_family(db: Session, client: OIDCClient, user: User, code: AuthorizationCode, scopes: List[str]) -> str:
    import uuid

    t = now()
    return _add(db, family=str(uuid.uuid4()), parent=None, code_id=code.id, client=client, user_id=user.id, scopes=scopes,
                auth_time=code.auth_time, amr=code.amr, absolute=t + timedelta(days=settings.OIDC_REFRESH_ABSOLUTE_DAYS))


def _add(db, *, family, parent, code_id, client, user_id, scopes, auth_time, amr, absolute: datetime) -> str:
    raw = _new_raw()
    t = now()
    db.add(RefreshToken(
        token_hash=_h(raw), family_id=family, parent_id=parent, code_id=code_id, client_pk=client.id, user_id=user_id,
        scopes=list(scopes), auth_time=auth_time, amr=list(amr), expires_at=min(t + timedelta(days=settings.OIDC_REFRESH_IDLE_DAYS), absolute),
        absolute_expires_at=absolute,
    ))
    return raw


def revoke_family(db: Session, family_id: str) -> int:
    return db.execute(
        update(RefreshToken).where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None)).values(revoked_at=now())
    ).rowcount


def revoke_for_code(db: Session, code_id: int) -> int:
    fams = [r[0] for r in db.query(RefreshToken.family_id).filter(RefreshToken.code_id == code_id).distinct()]
    return sum(revoke_family(db, f) for f in fams)


def revoke_for_user_client(db: Session, user_id: int, client_pk: int) -> int:
    return db.execute(
        update(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.client_pk == client_pk, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now())
    ).rowcount


def rotate(db: Session, client: OIDCClient, form: Dict[str, str], audit: Audit) -> Tuple[Dict, User]:
    if "refresh_token" not in client.grant_types:
        raise tokens.TokenError("unauthorized_client", "this client may not use refresh tokens")
    raw = form.get("refresh_token")
    if not raw or len(raw) > 128:
        raise tokens.TokenError("invalid_request", "refresh_token is required")
    tokens.keys.signing_key(db)  # 503 before anything is spent if signing is not configured

    row = db.query(RefreshToken).filter(RefreshToken.token_hash == _h(raw)).first()
    if row is None or row.client_pk != client.id:
        raise tokens.TokenError("invalid_grant", "invalid refresh token")

    spent = db.execute(
        update(RefreshToken).where(RefreshToken.id == row.id, RefreshToken.used_at.is_(None), RefreshToken.revoked_at.is_(None))
        .values(used_at=now())
    ).rowcount
    if spent != 1:
        if row.revoked_at is None:  # already rotated: a copy of this token is being replayed
            revoke_family(db, row.family_id)
            audit("OIDC_REFRESH_REUSE_DETECTED", row.user_id, {"client_id": client.client_id, "family": row.family_id})
        db.commit()
        raise tokens.TokenError("invalid_grant", "invalid refresh token")
    db.commit()  # the spend is durable before anything else can roll the transaction back

    user = db.get(User, row.user_id)
    try:
        t = now()
        if row.expires_at <= t or row.absolute_expires_at <= t:
            raise tokens.TokenError("invalid_grant", "invalid refresh token")
        if user is None or user.status != "active" or client.status != "active":
            raise tokens.TokenError("invalid_grant", "invalid refresh token")
        consent = get_consent(db, user.id, client)
        if consent is None or not set(row.scopes) <= set(consent.scopes) or "offline_access" not in client.allowed_scopes:
            revoke_family(db, row.family_id)  # consent withdrawn or client narrowed since the token was issued
            raise tokens.TokenError("invalid_grant", "access has been withdrawn")
        scopes = row.scopes
        if form.get("scope"):
            asked = [s for s in form["scope"].split(" ") if s]
            if not set(asked) <= set(row.scopes):
                raise tokens.TokenError("invalid_scope", "scope exceeds the original grant")
            scopes = [s for s in row.scopes if s in asked]
    except tokens.TokenError:
        db.commit()
        raise

    # Signing may end the transaction (key rotation bookkeeping), so sign first and write the successor afterwards.
    body = tokens.build_tokens(db, client, user, scopes=scopes, auth_time=row.auth_time, amr=row.amr, nonce=None)
    new_raw = _add(db, family=row.family_id, parent=row.id, code_id=row.code_id, client=client, user_id=user.id, scopes=scopes,
                   auth_time=row.auth_time, amr=row.amr, absolute=row.absolute_expires_at)
    body["refresh_token"] = new_raw
    audit("OIDC_TOKEN_REFRESHED", user.id, {"client_id": client.client_id, "family": row.family_id})
    return body, user
