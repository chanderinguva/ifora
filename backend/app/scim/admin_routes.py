"""Admin API for SCIM tokens (ADR 007 D1). Creating is super-admin only; revoking is any admin."""

import ipaddress
from datetime import datetime, timedelta, timezone
from typing import List, Optional

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
    read_only: bool = False
    users_only: bool = False
    allowed_cidrs: Optional[List[str]] = Field(None, max_length=20)
    hard_delete_after_days: Optional[int] = Field(None, ge=7, le=3650)


class Restrictions(BaseModel):
    read_only: Optional[bool] = None
    users_only: Optional[bool] = None
    allowed_cidrs: Optional[List[str]] = Field(None, max_length=20)  # [] clears the list
    hard_delete_after_days: Optional[int] = Field(None, ge=0, le=3650)  # 0 clears the policy (otherwise 7..3650)


class Rotate(BaseModel):
    overlap_hours: int = Field(24, ge=0, le=720)  # the old token keeps working this long; 0 = revoke at once


def _cidrs(values: Optional[List[str]]) -> Optional[List[str]]:
    if values is None:
        return None
    out = []
    for v in values:
        try:
            net = ipaddress.ip_network(v.strip(), strict=False)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"'{v}' is not an IP address or CIDR range")
        out.append(str(net))
    return sorted(set(out))


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
        read_only=body.read_only, users_only=body.users_only, allowed_cidrs=_cidrs(body.allowed_cidrs) or None,
        hard_delete_after_days=body.hard_delete_after_days,
    )
    db.add(t)
    db.flush()
    record(db, AuditAction.SCIM_TOKEN_CREATED, request, actor, t.id, "scim_token",
           {"name": name, "expires_in_days": body.expires_in_days, "read_only": body.read_only, "users_only": body.users_only,
            "allowed_cidrs": t.allowed_cidrs or [], "hard_delete_after_days": body.hard_delete_after_days})
    db.commit()
    db.refresh(t)
    out = t.to_dict()
    out["token"] = raw  # shown once; only the keyed hash is stored
    out["base_url"] = base_url()
    return out


@router.put("/tokens/{token_id}/restrictions")
def restrict_token(token_id: int, body: Restrictions, request: Request, db: Session = Depends(get_db), actor: User = Depends(_super_admin)):
    """Narrow or widen what a token may do. Super admin only; every change is audited with before and after."""
    t = db.get(ScimToken, token_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Token not found")
    changed = {}
    if body.read_only is not None and body.read_only != t.read_only:
        changed["read_only"] = [t.read_only, body.read_only]
        t.read_only = body.read_only
    if body.users_only is not None and body.users_only != t.users_only:
        changed["users_only"] = [t.users_only, body.users_only]
        t.users_only = body.users_only
    if body.allowed_cidrs is not None:
        new = _cidrs(body.allowed_cidrs) or None
        if new != (t.allowed_cidrs or None):
            changed["allowed_cidrs"] = [t.allowed_cidrs or [], new or []]
            t.allowed_cidrs = new
    if body.hard_delete_after_days is not None:
        days = body.hard_delete_after_days or None
        if days is not None and days < 7:
            raise HTTPException(status_code=422, detail="hard_delete_after_days must be at least 7 (or 0 to turn it off)")
        if days != t.hard_delete_after_days:
            changed["hard_delete_after_days"] = [t.hard_delete_after_days, days]
            t.hard_delete_after_days = days
    if changed:
        record(db, AuditAction.SCIM_TOKEN_RESTRICTED, request, actor, t.id, "scim_token", {"name": t.name, "changed": changed})
    db.commit()
    return t.to_dict()


@router.post("/tokens/{token_id}/rotate", status_code=201)
def rotate_token(token_id: int, body: Rotate, request: Request, db: Session = Depends(get_db), actor: User = Depends(_super_admin)):
    """Issue a replacement with the same restrictions. The old token keeps working for `overlap_hours` (never longer than
    its own expiry) so the IdP can be switched over without a gap."""
    old = db.get(ScimToken, token_id)
    if old is None:
        raise HTTPException(status_code=404, detail="Token not found")
    if old.status != "active":
        raise HTTPException(status_code=409, detail="Only an active token can be rotated")
    if old.replaced_by_id is not None:
        raise HTTPException(status_code=409, detail="This token was already rotated")
    now = datetime.now(timezone.utc)
    active = [t for t in db.query(ScimToken).filter(ScimToken.revoked_at.is_(None)).all() if t.status == "active"]
    if len(active) >= MAX_ACTIVE_TOKENS:
        raise HTTPException(status_code=409, detail=f"At most {MAX_ACTIVE_TOKENS} active tokens; revoke one first")
    raw = scim_auth.new_token()
    new = ScimToken(
        name=old.name, token_hash=scim_auth.hash_token(raw), token_prefix=raw[: len(scim_auth.TOKEN_PREFIX) + 4],
        created_by_user_id=actor.id, expires_at=old.expires_at, read_only=old.read_only, users_only=old.users_only,
        allowed_cidrs=old.allowed_cidrs, hard_delete_after_days=old.hard_delete_after_days,
    )
    db.add(new)
    db.flush()
    old.replaced_by_id = new.id
    if body.overlap_hours == 0:
        old.revoked_at = now
    else:
        end = now + timedelta(hours=body.overlap_hours)
        old.expires_at = min(old.expires_at, end) if old.expires_at else end
    record(db, AuditAction.SCIM_TOKEN_ROTATED, request, actor, old.id, "scim_token",
           {"name": old.name, "new_token_id": new.id, "overlap_hours": body.overlap_hours})
    db.commit()
    db.refresh(new)
    out = new.to_dict()
    out["token"] = raw
    out["base_url"] = base_url()
    out["replaces"] = old.to_dict()
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
