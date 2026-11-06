"""OIDC public endpoints (mounted at the issuer root, not under /api/v1) and signing-key administration."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.auth.deps import require_admin
from backend.app.db import get_db
from backend.app.oidc import keys
from backend.app.oidc.models import KeyStatus, SigningKey
from backend.app.config import settings

public_router = APIRouter(tags=["oidc"])
admin_router = APIRouter(prefix="/admin/oidc", tags=["oidc-admin"])


@public_router.get("/oauth/jwks", include_in_schema=True)
def jwks(db: Session = Depends(get_db)):
    """Public signing keys. Unauthenticated, credential-free CORS (any origin may read public keys)."""
    try:
        body = keys.public_jwks(db)
    except keys.KeyConfigError:
        raise HTTPException(status_code=503, detail="OIDC signing is not configured")
    return JSONResponse(
        body,
        headers={
            "Cache-Control": f"public, max-age={settings.OIDC_JWKS_CACHE_SECONDS}",
            "Access-Control-Allow-Origin": "*",
        },
    )


def _super_admin(user=Depends(require_admin)):
    if not user.is_super_admin:
        raise HTTPException(status_code=403, detail="Forbidden")
    return user


@admin_router.get("/keys")
def list_keys(user=Depends(_super_admin), db: Session = Depends(get_db)):
    keys.advance(db)
    rows = db.query(SigningKey).order_by(SigningKey.created_at.desc(), SigningKey.id.desc()).all()
    return {"items": [r.to_admin_dict() for r in rows], "overlap_seconds": keys.overlap_seconds()}


class RotateBody(BaseModel):
    emergency: bool = False
    confirm: bool = False  # emergency rotation invalidates tokens already issued; require an explicit flag


@admin_router.post("/keys/rotate", status_code=201)
def rotate_key(body: RotateBody, request: Request, user=Depends(_super_admin), db: Session = Depends(get_db)):
    if body.emergency and not body.confirm:
        raise HTTPException(status_code=400, detail="Emergency rotation revokes all current keys; set confirm=true")

    def audit(name: str, meta: Optional[dict] = None):
        record(db, AuditAction(name), request, user, None, "signing_key", meta)

    try:
        new = keys.rotate(db, emergency=body.emergency, audit=audit)
    except keys.KeyConfigError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return new.to_admin_dict()
