"""Admin API tokens: create, list, revoke (ADR 024). Browser session only; a token can never manage tokens."""

import ipaddress
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app import ratelimit
from backend.app.admin_roles.resolve import roles_of
from backend.app.api_tokens import service
from backend.app.api_tokens.models import ApiToken
from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.auth.deps import require_admin_session
from backend.app.db import get_db
from backend.app.users.model import User

router = APIRouter(prefix="/admin/api-tokens", tags=["api-tokens"])


class TokenCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=256)  # the creator proves it is them, not a hijacked session
    expires_in_days: int = Field(service.DEFAULT_DAYS, ge=1, le=service.MAX_DAYS)
    read_only: bool = False
    allowed_cidrs: Optional[List[str]] = Field(None, max_length=20)


def _cidrs(values: Optional[List[str]]) -> Optional[List[str]]:
    out = []
    for v in values or []:
        try:
            out.append(str(ipaddress.ip_network(v.strip(), strict=False)))
        except ValueError:
            raise HTTPException(status_code=422, detail=f"'{v}' is not an IP address or CIDR range")
    return sorted(set(out)) or None


def _sees_all(db: Session, user: User) -> bool:
    return user.is_super_admin or "org_admin" in roles_of(db, user.id)


@router.get("")
def list_tokens(all: bool = False, db: Session = Depends(get_db), user: User = Depends(require_admin_session)):
    q = db.query(ApiToken)
    if all:
        if not _sees_all(db, user):
            raise HTTPException(status_code=403, detail="Only a super administrator or organization administrator can list everyone's tokens")
    else:
        q = q.filter(ApiToken.user_id == user.id)
    rows = q.order_by(ApiToken.id.desc()).limit(500).all()
    owners = {u.id: u for u in db.query(User).filter(User.id.in_({t.user_id for t in rows})).all()} if rows else {}
    items = []
    for t in rows:
        d = t.to_dict()
        o = owners.get(t.user_id)
        d["owner"] = {"id": o.id, "name": f"{o.first_name} {o.last_name}", "email": o.email} if o else None
        items.append(d)
    return {"items": items, "max_days": service.MAX_DAYS, "default_days": service.DEFAULT_DAYS, "max_active": service.MAX_ACTIVE_PER_USER}


@router.post("", status_code=201)
def create_token(body: TokenCreate, request: Request, db: Session = Depends(get_db), user: User = Depends(require_admin_session)):
    ratelimit.check("api_token_pw", str(user.id), 5)
    if not user.verify_password(body.password):
        ratelimit.hit("api_token_pw", str(user.id), 900)
        raise HTTPException(status_code=403, detail="Password is incorrect")
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Name is required")
    now = datetime.now(timezone.utc)
    active = db.query(ApiToken).filter(ApiToken.user_id == user.id, ApiToken.revoked_at.is_(None), ApiToken.expires_at > now).count()
    if active >= service.MAX_ACTIVE_PER_USER:
        raise HTTPException(status_code=409, detail=f"At most {service.MAX_ACTIVE_PER_USER} active tokens; revoke one first")
    raw = service.new_token()
    t = ApiToken(user_id=user.id, name=name, token_hash=service.hash_token(raw), token_prefix=raw[: len(service.TOKEN_PREFIX) + 4],
                 read_only=body.read_only, allowed_cidrs=_cidrs(body.allowed_cidrs), expires_at=now + timedelta(days=body.expires_in_days))
    db.add(t)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="You already have an active token with this name")
    record(db, AuditAction.API_TOKEN_CREATED, request, user, t.id, "api_token",
           {"name": name, "expires_in_days": body.expires_in_days, "read_only": body.read_only, "allowed_cidrs": t.allowed_cidrs or [], "token_prefix": t.token_prefix})
    db.commit()
    db.refresh(t)
    out = t.to_dict()
    out["token"] = raw  # shown once; only the keyed hash is stored
    return out


@router.delete("/{token_id}")
def revoke_token(token_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_admin_session)):
    t = db.get(ApiToken, token_id)
    if t is None or (t.user_id != user.id and not _sees_all(db, user)):
        raise HTTPException(status_code=404, detail="Token not found")
    if t.revoked_at is None:
        t.revoked_at = datetime.now(timezone.utc)
        record(db, AuditAction.API_TOKEN_REVOKED, request, user, t.id, "api_token", {"name": t.name, "owner_user_id": t.user_id, "token_prefix": t.token_prefix})
        db.commit()
    return t.to_dict()
