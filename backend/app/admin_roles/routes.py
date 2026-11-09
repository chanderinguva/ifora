"""Administrator roles: who has which, and what the signed-in admin may do (ADR 014)."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.admin_roles import permissions
from backend.app.admin_roles.models import AdminRoleAssignment
from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.auth.deps import get_current_user, require_admin
from backend.app.db import get_db
from backend.app.users.model import User

router = APIRouter(prefix="/admin/roles", tags=["admin-roles"])
me_router = APIRouter(prefix="/me", tags=["admin-roles"])


def roles_of(db: Session, user_id: int) -> List[str]:
    return sorted(r for (r,) in db.query(AdminRoleAssignment.role).filter(AdminRoleAssignment.user_id == user_id))


@me_router.get("/admin-access")
def my_access(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """What the signed-in administrator can do, so the UI can hide what would only be refused."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Forbidden")
    if user.is_super_admin:
        return {"super_admin": True, "roles": [], "implicit": False, "access": {a: permissions.WRITE for a in permissions.AREA_NAMES}}
    roles = roles_of(db, user.id)
    return {"super_admin": False, "roles": roles, "implicit": not roles, "access": permissions.effective(roles)}


def _super(actor: User) -> None:
    if not actor.is_super_admin:
        raise HTTPException(status_code=403, detail="Only a super administrator can assign administrator roles")


@router.get("")
def catalog(actor: User = Depends(require_admin)):
    _super(actor)
    return {"items": [{"id": k, "label": v["label"], "description": v["description"], "access": v["access"]} for k, v in permissions.ROLES.items()]}


class RolesBody(BaseModel):
    roles: List[str] = Field(default_factory=list, max_length=len(permissions.ROLE_IDS))


def _target(db: Session, user_id: int) -> User:
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="User not found")
    return u


@router.get("/users/{user_id}")
def get_user_roles(user_id: int, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    _super(actor)
    u = _target(db, user_id)
    roles = roles_of(db, u.id)
    return {"user_id": u.id, "roles": roles, "implicit": not roles, "super_admin": u.is_super_admin, "is_admin": u.is_admin}


@router.put("/users/{user_id}")
def set_user_roles(user_id: int, body: RolesBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    _super(actor)
    u = _target(db, user_id)
    if not u.is_admin or u.is_super_admin:
        raise HTTPException(status_code=400, detail="Roles apply to administrators who are not super administrators")
    wanted = sorted(set(body.roles))
    if any(r not in permissions.ROLES for r in wanted):
        raise HTTPException(status_code=400, detail="Unknown role")
    before = roles_of(db, u.id)
    if wanted != before:
        db.query(AdminRoleAssignment).filter(AdminRoleAssignment.user_id == u.id).delete()
        for r in wanted:
            db.add(AdminRoleAssignment(user_id=u.id, role=r, granted_by=actor.id))
        record(db, AuditAction.ADMIN_ROLES_UPDATED, request, actor, u.id, "user", {"from": before or ["org_admin (default)"], "to": wanted or ["org_admin (default)"]})
        db.commit()
    return {"user_id": u.id, "roles": wanted, "implicit": not wanted}
