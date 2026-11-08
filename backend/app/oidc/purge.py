"""Delete OIDC rows that can no longer matter (ADR 005 M6). Safe to run any time and by several workers at once.

What is kept on purpose, because it still protects someone:
- refresh tokens until their FAMILY's absolute limit: a rotated token must stay recognisable so presenting it
  again revokes the family (reuse detection);
- authorization codes that refresh tokens were issued from, so a replayed code can still revoke those families.
Everything else is deleted a grace period after it expired.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import delete, exists, select
from sqlalchemy.orm import Session

from backend.app.oidc.models import AccessToken, AuthorizationCode, PendingAuthRequest, RefreshToken
from backend.app.tenancy import unscoped

GRACE = timedelta(hours=1)
CODE_GRACE = timedelta(days=1)  # replaying a code this old gets invalid_grant, just without revoking anything


def purge(db: Session, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    out = {}
    with unscoped(db):
        out["pending_requests"] = db.execute(
            delete(PendingAuthRequest).where(PendingAuthRequest.expires_at < now - GRACE)
        ).rowcount
        from backend.app.saml.models import SamlPendingRequest

        out["saml_pending_requests"] = db.execute(delete(SamlPendingRequest).where(SamlPendingRequest.expires_at < now - GRACE)).rowcount
        out["access_tokens"] = db.execute(delete(AccessToken).where(AccessToken.expires_at < now - GRACE)).rowcount
        out["refresh_tokens"] = db.execute(
            delete(RefreshToken).where(RefreshToken.absolute_expires_at < now)
        ).rowcount
        still_needed = exists(select(RefreshToken.id).where(RefreshToken.code_id == AuthorizationCode.id))
        out["codes"] = db.execute(
            delete(AuthorizationCode).where(AuthorizationCode.expires_at < now - CODE_GRACE, ~still_needed)
        ).rowcount
        from backend.app.swa.purge import purge_unentitled

        out["swa_credentials"] = purge_unentitled(db)
        db.commit()
    return out
