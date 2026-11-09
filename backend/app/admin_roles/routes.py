"""Administrator roles: who has which, and what the signed-in admin may do (ADR 014)."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.admin_roles import permissions
from backend.app.admin_roles import resolve
from backend.app.admin_roles.models import AdminRoleAssignment, GroupAdminRole
from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.auth.deps import get_current_user, require_admin
from backend.app.db import get_db
from backend.app.users.model import User

router = APIRouter(prefix="/admin/roles", tags=["admin-roles"])
me_router = APIRouter(prefix="/me", tags=["admin-roles"])


def roles_of(db: Session, user_id: int) -> List[str]:
    """Direct roles only (what the user page edits). Effective roles, with group-carried ones, are in resolve.roles_of."""
    return resolve.direct_roles(db, user_id)


@me_router.get("/admin-access")
def my_access(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """What the signed-in administrator can do, so the UI can hide what would only be refused."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Forbidden")
    if user.is_super_admin:
        return {"super_admin": True, "roles": [], "implicit": False, "access": {a: permissions.WRITE for a in permissions.AREA_NAMES}}
    sources = resolve.role_sources(db, user.id)
    roles = sorted(sources)
    return {"super_admin": False, "roles": roles, "sources": sources, "implicit": False, "access": permissions.effective(roles)}


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
    direct = roles_of(db, u.id)
    sources = resolve.role_sources(db, u.id)
    return {"user_id": u.id, "roles": direct, "effective_roles": sorted(sources), "sources": sources, "implicit": False,
            "super_admin": u.is_super_admin, "is_admin": u.is_admin}


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
        record(db, AuditAction.ADMIN_ROLES_UPDATED, request, actor, u.id, "user", {"from": before, "to": wanted})
        db.commit()
    return {"user_id": u.id, "roles": wanted, "implicit": False}


# ---- roles carried by a group (ADR 019) ------------------------------------------------------------------------

def _group(db: Session, group_id: int):
    from backend.app.groups.model import Group

    g = db.get(Group, group_id)
    if g is None:
        raise HTTPException(status_code=404, detail="Group not found")
    return g


def _group_roles(db: Session, group_id: int) -> List[str]:
    return sorted(r for (r,) in db.query(GroupAdminRole.role).filter(GroupAdminRole.group_id == group_id))


@router.get("/groups")
def groups_with_roles(db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    _super(actor)
    from backend.app.groups.model import Group

    rows = db.query(Group.id, Group.name, GroupAdminRole.role).join(GroupAdminRole, GroupAdminRole.group_id == Group.id).order_by(Group.name).all()
    out: dict = {}
    for gid, name, role in rows:
        out.setdefault(gid, {"group_id": gid, "name": name, "roles": []})["roles"].append(role)
    return {"items": list(out.values())}


@router.get("/groups/{group_id}")
def get_group_roles(group_id: int, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    _super(actor)
    g = _group(db, group_id)
    return {"group_id": g.id, "type": g.type, "roles": _group_roles(db, g.id), "can_carry_roles": g.type == "team" and not g.is_system_group}


@router.put("/groups/{group_id}")
def set_group_roles(group_id: int, body: RolesBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    """Every member of the group gets these roles. Only team groups may carry roles; changing them takes effect on members' next request."""
    _super(actor)
    g = _group(db, group_id)
    wanted = sorted(set(body.roles))
    if any(r not in permissions.ROLES for r in wanted):
        raise HTTPException(status_code=400, detail="Unknown role")
    if wanted and (g.type != "team" or g.is_system_group):
        raise HTTPException(status_code=409, detail="Only team groups can carry administrator roles (set the group type to Team first)")
    before = _group_roles(db, g.id)
    if wanted != before:
        db.query(GroupAdminRole).filter(GroupAdminRole.group_id == g.id).delete()
        for r in wanted:
            db.add(GroupAdminRole(group_id=g.id, role=r, granted_by=actor.id))
        record(db, AuditAction.ADMIN_ROLES_UPDATED, request, actor, g.id, "group", {"from": before, "to": wanted, "members": g.member_count})
        db.commit()
    return {"group_id": g.id, "roles": wanted}
