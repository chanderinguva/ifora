"""Admin API for SCIM tokens (ADR 007 D1). Creating is super-admin only; revoking is any admin."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.auth.deps import require_admin
from backend.app.db import get_db
from backend.app.scim import auth as scim_auth
from backend.app.scim.mapping import base_url
from backend.app.scim.models import ScimToken
from backend.app.users.model import User

router = APIRouter(prefix="/admin/scim", tags=["scim"])
MAX_ACTIVE_TOKENS = 20


class TokenCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    expires_in_days: Optional[int] = Field(None, ge=1, le=3650)


def _super_admin(user: User = Depends(require_admin)) -> User:
    if not user.is_super_admin:
        raise HTTPException(status_code=403, detail="Only a super administrator can create SCIM tokens")
    return user


@router.get("/tokens")
def list_tokens(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    rows = db.query(ScimToken).order_by(ScimToken.id.desc()).limit(200).all()
    return {"items": [t.to_dict() for t in rows], "base_url": base_url()}


@router.post("/tokens", status_code=201)
def create_token(body: TokenCreate, request: Request, db: Session = Depends(get_db), actor: User = Depends(_super_admin)):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Name is required")
    now = datetime.now(timezone.utc)
    active = [t for t in db.query(ScimToken).filter(ScimToken.revoked_at.is_(None)).all() if t.status == "active"]
    if len(active) >= MAX_ACTIVE_TOKENS:
        raise HTTPException(status_code=409, detail=f"At most {MAX_ACTIVE_TOKENS} active tokens; revoke one first")
    raw = scim_auth.new_token()
    t = ScimToken(
        name=name, token_hash=scim_auth.hash_token(raw), token_prefix=raw[: len(scim_auth.TOKEN_PREFIX) + 4],
        created_by_user_id=actor.id,
        expires_at=now + timedelta(days=body.expires_in_days) if body.expires_in_days else None,
    )
    db.add(t)
    db.flush()
    record(db, AuditAction.SCIM_TOKEN_CREATED, request, actor, t.id, "scim_token",
           {"name": name, "expires_in_days": body.expires_in_days})
    db.commit()
    db.refresh(t)
    out = t.to_dict()
    out["token"] = raw  # shown once; only the keyed hash is stored
    out["base_url"] = base_url()
    return out


@router.delete("/tokens/{token_id}")
def revoke_token(token_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    t = db.get(ScimToken, token_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Token not found")
    if t.revoked_at is None:
        t.revoked_at = datetime.now(timezone.utc)
        record(db, AuditAction.SCIM_TOKEN_REVOKED, request, actor, t.id, "scim_token", {"name": t.name})
        db.commit()
    return t.to_dict()
