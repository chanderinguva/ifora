"""Admin API: network zones and per-application authentication policies (ADR 013)."""

import ipaddress
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.applications.models import Application
from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.auth.deps import require_admin
from backend.app.db import get_db
from backend.app.policies.models import AppAuthPolicy, NetworkZone
from backend.app.users.model import User

zones_router = APIRouter(prefix="/admin/network-zones", tags=["policies"])
policy_router = APIRouter(prefix="/admin/applications", tags=["policies"])

MAX_CIDRS = 50
POLICY_MODES = ("oidc", "saml", "swa")


def _now():
    return datetime.now(timezone.utc)


class ZoneBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    cidrs: List[str] = Field(..., min_length=1, max_length=MAX_CIDRS)

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("name is required")
        return v

    @field_validator("cidrs")
    @classmethod
    def _cidrs(cls, v):
        out = []
        for c in v:
            try:
                out.append(str(ipaddress.ip_network(c.strip(), strict=False)))
            except ValueError:
                raise ValueError(f"'{c}' is not a valid IP address or CIDR range")
        return list(dict.fromkeys(out))


def _zone_dict(z: NetworkZone) -> dict:
    return {"id": z.id, "name": z.name, "cidrs": z.cidrs or [], "updated_at": z.updated_at.isoformat() if z.updated_at else None}


def _zone_or_404(db: Session, zone_id: int) -> NetworkZone:
    z = db.get(NetworkZone, zone_id)
    if z is None:
        raise HTTPException(status_code=404, detail="Network zone not found")
    return z


@zones_router.get("")
def list_zones(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return {"items": [_zone_dict(z) for z in db.query(NetworkZone).order_by(NetworkZone.name).all()]}


@zones_router.post("", status_code=201)
def create_zone(body: ZoneBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    z = NetworkZone(name=body.name, cidrs=body.cidrs)
    db.add(z)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A network zone with this name already exists")
    record(db, AuditAction.NETWORK_ZONE_CREATED, request, actor, z.id, "network_zone", {"name": z.name, "cidrs": z.cidrs})
    db.commit()
    return _zone_dict(z)


@zones_router.put("/{zone_id}")
def update_zone(zone_id: int, body: ZoneBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    z = _zone_or_404(db, zone_id)
    z.name, z.cidrs, z.updated_at = body.name, body.cidrs, _now()
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A network zone with this name already exists")
    record(db, AuditAction.NETWORK_ZONE_UPDATED, request, actor, z.id, "network_zone", {"name": z.name, "cidrs": z.cidrs})
    db.commit()
    return _zone_dict(z)


def _used_by(db: Session, zone_id: int) -> List[int]:
    return [p.application_id for p in db.query(AppAuthPolicy).all() if zone_id in (p.allowed_zone_ids or []) or zone_id in (p.blocked_zone_ids or [])]


@zones_router.delete("/{zone_id}", status_code=204)
def delete_zone(zone_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    z = _zone_or_404(db, zone_id)
    if _used_by(db, z.id):
        # Deleting an allow-list zone would silently widen or lock out an app; make the admin detach it first.
        raise HTTPException(status_code=409, detail="This zone is used by an application policy; remove it there first")
    record(db, AuditAction.NETWORK_ZONE_DELETED, request, actor, z.id, "network_zone", {"name": z.name})
    db.delete(z)
    db.commit()


# ---- per-application policy ------------------------------------------------------------------------------------

class PolicyBody(BaseModel):
    require_mfa: bool = False
    reauth_minutes: Optional[int] = Field(None, ge=5, le=1440)
    allowed_zone_ids: List[int] = Field(default_factory=list, max_length=20)
    blocked_zone_ids: List[int] = Field(default_factory=list, max_length=20)


def _app_or_404(db: Session, app_id: int) -> Application:
    a = db.get(Application, app_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return a


def _policy_dict(p: Optional[AppAuthPolicy]) -> dict:
    if p is None:
        return {"configured": False, "require_mfa": False, "reauth_minutes": None, "allowed_zone_ids": [], "blocked_zone_ids": []}
    return {"configured": True, "require_mfa": p.require_mfa, "reauth_minutes": p.reauth_minutes,
            "allowed_zone_ids": p.allowed_zone_ids or [], "blocked_zone_ids": p.blocked_zone_ids or []}


@policy_router.get("/{app_id}/policy")
def get_policy(app_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    _app_or_404(db, app_id)
    return _policy_dict(db.query(AppAuthPolicy).filter(AppAuthPolicy.application_id == app_id).first())


@policy_router.put("/{app_id}/policy")
def put_policy(app_id: int, body: PolicyBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    a = _app_or_404(db, app_id)
    if a.sign_on_mode not in POLICY_MODES:
        raise HTTPException(status_code=400, detail="Authentication policies apply to OIDC, SAML and SWA applications")
    ids = set(body.allowed_zone_ids) | set(body.blocked_zone_ids)
    if ids and db.query(NetworkZone.id).filter(NetworkZone.id.in_(ids)).count() != len(ids):
        raise HTTPException(status_code=400, detail="Unknown network zone")
    if set(body.allowed_zone_ids) & set(body.blocked_zone_ids):
        raise HTTPException(status_code=400, detail="A zone cannot be both allowed and blocked")
    p = db.query(AppAuthPolicy).filter(AppAuthPolicy.application_id == app_id).first()
    if p is None:
        p = AppAuthPolicy(application_id=app_id)
        db.add(p)
    p.require_mfa, p.reauth_minutes = body.require_mfa, body.reauth_minutes
    p.allowed_zone_ids, p.blocked_zone_ids, p.updated_at = sorted(set(body.allowed_zone_ids)), sorted(set(body.blocked_zone_ids)), _now()
    record(db, AuditAction.APPLICATION_POLICY_UPDATED, request, actor, a.id, "application", {"name": a.name, **{k: v for k, v in _policy_dict(p).items() if k != "configured"}})
    db.commit()
    return _policy_dict(p)


@policy_router.delete("/{app_id}/policy", status_code=204)
def delete_policy(app_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    a = _app_or_404(db, app_id)
    p = db.query(AppAuthPolicy).filter(AppAuthPolicy.application_id == app_id).first()
    if p is not None:
        db.delete(p)
        record(db, AuditAction.APPLICATION_POLICY_REMOVED, request, actor, a.id, "application", {"name": a.name})
        db.commit()
