"""Admin API: network zones and per-application authentication policies (ADR 013)."""

import ipaddress
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.applications.models import Application
from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.auth.deps import require_admin
from backend.app.auth.stepup import require_stepup
from backend.app.config import settings
from backend.app.db import get_db
from backend.app import ratelimit
from backend.app.policies import engine
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


@zones_router.post("", status_code=201, dependencies=[Depends(require_stepup)])
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


@zones_router.put("/{zone_id}", dependencies=[Depends(require_stepup)])
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


@zones_router.delete("/{zone_id}", status_code=204, dependencies=[Depends(require_stepup)])
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


def _check_policy_body(db: Session, body: "PolicyBody") -> None:
    ids = set(body.allowed_zone_ids) | set(body.blocked_zone_ids)
    if ids and db.query(NetworkZone.id).filter(NetworkZone.id.in_(ids)).count() != len(ids):
        raise HTTPException(status_code=400, detail="Unknown network zone")
    if set(body.allowed_zone_ids) & set(body.blocked_zone_ids):
        raise HTTPException(status_code=400, detail="A zone cannot be both allowed and blocked")


@policy_router.get("/{app_id}/policy")
def get_policy(app_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    _app_or_404(db, app_id)
    return _policy_dict(db.query(AppAuthPolicy).filter(AppAuthPolicy.application_id == app_id).first())


@policy_router.put("/{app_id}/policy", dependencies=[Depends(require_stepup)])
def put_policy(app_id: int, body: PolicyBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    a = _app_or_404(db, app_id)
    if a.sign_on_mode not in POLICY_MODES:
        raise HTTPException(status_code=400, detail="Authentication policies apply to OIDC, SAML and SWA applications")
    _check_policy_body(db, body)
    p = db.query(AppAuthPolicy).filter(AppAuthPolicy.application_id == app_id).first()
    if p is None:
        p = AppAuthPolicy(application_id=app_id)
        db.add(p)
    p.require_mfa, p.reauth_minutes = body.require_mfa, body.reauth_minutes
    p.allowed_zone_ids, p.blocked_zone_ids, p.updated_at = sorted(set(body.allowed_zone_ids)), sorted(set(body.blocked_zone_ids)), _now()
    record(db, AuditAction.APPLICATION_POLICY_UPDATED, request, actor, a.id, "application", {"name": a.name, **{k: v for k, v in _policy_dict(p).items() if k != "configured"}})
    db.commit()
    return _policy_dict(p)


@policy_router.delete("/{app_id}/policy", status_code=204, dependencies=[Depends(require_stepup)])
def delete_policy(app_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    a = _app_or_404(db, app_id)
    p = db.query(AppAuthPolicy).filter(AppAuthPolicy.application_id == app_id).first()
    if p is not None:
        db.delete(p)
        record(db, AuditAction.APPLICATION_POLICY_REMOVED, request, actor, a.id, "application", {"name": a.name})
        db.commit()


# ---- simulation (IFORA-33) -------------------------------------------------------------------------------------

_AMR_VALUES = ("pwd", "otp", "mfa", "hwk", "user")
_EXPLAIN = {
    "no_policy": "No authentication policy is set, so the sign-in is allowed.",
    "blocked_zone": "The source address is inside a network zone that is always blocked for this application.",
    "allowed_zones": "The application only accepts sign-ins from approved network zones and this address is in none of them.",
    "require_mfa": "The policy requires multi-factor authentication and this sign-in did not use it.",
    "reauth_minutes": "The policy requires a recent sign-in and this session's sign-in is older than that.",
    "passed": "Every condition of the policy is met.",
}


class SimulateBody(BaseModel):
    user_id: int
    source_ip: str = Field(..., max_length=64)
    amr: List[str] = Field(default_factory=lambda: ["pwd"], max_length=5)
    session_age_minutes: int = Field(0, ge=0, le=10080)
    policy: Optional[PolicyBody] = None  # a draft to judge instead of the stored policy; nothing is saved

    @field_validator("source_ip")
    @classmethod
    def _ip(cls, v):
        try:
            return str(ipaddress.ip_address(v.strip()))
        except ValueError:
            raise ValueError("source_ip must be an IPv4 or IPv6 address")

    @field_validator("amr")
    @classmethod
    def _amr(cls, v):
        bad = [x for x in v if x not in _AMR_VALUES]
        if bad:
            raise ValueError(f"unknown authentication method(s): {', '.join(bad)}")
        return list(dict.fromkeys(v))


def _decision_dict(d: engine.Decision) -> dict:
    return {"decision": d.kind, "reason": d.reason, "rule": d.rule, "explanation": _EXPLAIN.get(d.rule, "")}


@policy_router.post("/{app_id}/policy/simulate")
def simulate_policy(app_id: int, body: SimulateBody, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    """Judge a hypothetical sign-in with the real `engine.evaluate`. Read-only: nothing is written and no denial is audited.
    Needs the same permission as editing the policy (this route sits under /admin/applications, a write area)."""
    ratelimit.check("policy_simulate", str(actor.id), settings.RATE_LIMIT_POLICY_SIMULATE)
    ratelimit.hit("policy_simulate", str(actor.id), 60)
    _app_or_404(db, app_id)
    user = db.get(User, body.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    session = SimpleNamespace(amr=body.amr, auth_time=datetime.now(timezone.utc) - timedelta(minutes=body.session_age_minutes))
    stored = db.query(AppAuthPolicy).filter(AppAuthPolicy.application_id == app_id).first()
    stored_decision = engine.evaluate(db, app_id, user, session, body.source_ip)
    out = {"user": {"id": user.id, "email": user.email}, "source_ip": body.source_ip, "amr": body.amr, "session_age_minutes": body.session_age_minutes,
           "stored_policy": _policy_dict(stored), "stored": _decision_dict(stored_decision), "draft_policy": None, "draft": None, "changed": False}
    if body.policy is not None:
        _check_policy_body(db, body.policy)
        draft = SimpleNamespace(require_mfa=body.policy.require_mfa, reauth_minutes=body.policy.reauth_minutes,
                                allowed_zone_ids=sorted(set(body.policy.allowed_zone_ids)), blocked_zone_ids=sorted(set(body.policy.blocked_zone_ids)))
        d = engine.evaluate(db, app_id, user, session, body.source_ip, policy=draft)
        out["draft_policy"] = {"configured": True, **{k: getattr(draft, k) for k in ("require_mfa", "reauth_minutes", "allowed_zone_ids", "blocked_zone_ids")}}
        out["draft"] = _decision_dict(d)
        out["changed"] = d.kind != stored_decision.kind  # the outcome (allow / deny / reauth), not which rule produced it
    return out
