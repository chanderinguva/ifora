"""A user's own view of the applications they authorised, and the power to withdraw that."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.auth.deps import get_current_user
from backend.app.db import get_db
from backend.app.oidc import refresh
from backend.app.oidc.models import OIDCClient, OIDCConsent
from backend.app.users.model import User

router = APIRouter(prefix="/me/consents", tags=["oidc"])


@router.get("")
def list_consents(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (db.query(OIDCConsent, OIDCClient).join(OIDCClient, OIDCClient.id == OIDCConsent.client_pk)
            .filter(OIDCConsent.user_id == user.id, OIDCConsent.revoked_at.is_(None), OIDCClient.first_party.is_(False))
            .order_by(OIDCConsent.created_at.desc()).all())
    return {"items": [{"client_pk": c.id, "name": c.name, "description": c.description, "scopes": k.scopes,
                       "granted_at": k.created_at.isoformat()} for k, c in rows]}


@router.delete("/{client_pk}")
def withdraw(client_pk: int, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    consent = db.query(OIDCConsent).filter(OIDCConsent.user_id == user.id, OIDCConsent.client_pk == client_pk,
                                           OIDCConsent.revoked_at.is_(None)).first()
    client = db.get(OIDCClient, client_pk)
    if consent is None or client is None or client.first_party:
        raise HTTPException(status_code=404, detail="Not found")
    from backend.app.oidc.authorize import now

    consent.revoked_at = now()
    ended = refresh.revoke_for_user_client(db, user.id, client_pk)
    record(db, AuditAction.OIDC_CONSENT_REVOKED, request, user, user.id, "user", {"client_id": client.client_id, "refresh_tokens_revoked": ended})
    db.commit()
    return {"success": True}
