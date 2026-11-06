"""Admin group management API."""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, insert
from sqlalchemy.orm import Session

from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.auth.deps import require_admin
from backend.app.db import get_db
from backend.app.groups.model import Group, user_group_association
from backend.app.users.model import User

router = APIRouter(prefix="/admin/groups", tags=["groups"])


class GroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)


class GroupUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)


class MemberAdd(BaseModel):
    user_id: int


def _group_or_404(db: Session, group_id: int) -> Group:
    g = db.get(Group, group_id)
    if g is None:
        raise HTTPException(status_code=404, detail="Group not found")
    return g


def _detail(g: Group) -> dict:
    d = g.to_dict()
    d["members"] = [
        {"id": u.id, "email": u.email, "first_name": u.first_name, "last_name": u.last_name}
        for u in sorted(g.members, key=lambda u: u.id)
    ]
    return d


def _name_taken(db: Session, name: str, exclude_id: Optional[int] = None) -> bool:
    q = db.query(Group.id).filter(func.lower(Group.name) == name.lower())
    if exclude_id is not None:
        q = q.filter(Group.id != exclude_id)
    return q.first() is not None


@router.get("")
def list_groups(
    q: Optional[str] = Query(None, max_length=100),
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    query = db.query(Group)
    if q:
        query = query.filter(func.lower(Group.name).like(f"%{q.lower().replace('%', '').replace('_', '')}%"))
    total = query.count()
    items = query.order_by(Group.id).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [g.to_dict() for g in items], "total": total, "page": page, "page_size": page_size}


@router.post("", status_code=201)
def create_group(
    body: GroupCreate, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)
):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Name is required")
    if _name_taken(db, name):
        raise HTTPException(status_code=409, detail="Group name already in use")
    g = Group(name=name, description=body.description)
    db.add(g)
    db.flush()
    record(db, AuditAction.GROUP_CREATED, request, actor, g.id, "group", {"name": name})
    db.commit()
    db.refresh(g)
    return _detail(g)


@router.get("/{group_id}")
def get_group(group_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return _detail(_group_or_404(db, group_id))


@router.patch("/{group_id}")
def update_group(
    group_id: int,
    body: GroupUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
):
    g = _group_or_404(db, group_id)
    if g.is_system_group:
        raise HTTPException(status_code=403, detail="System groups cannot be modified")
    changed = {}
    if body.name is not None and body.name.strip() != g.name:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="Name is required")
        if _name_taken(db, name, g.id):
            raise HTTPException(status_code=409, detail="Group name already in use")
        g.name = name
        changed["name"] = name
    if body.description is not None:
        g.description = body.description
        changed["description"] = True
    if changed:
        record(db, AuditAction.GROUP_UPDATED, request, actor, g.id, "group", {"changed": changed})
    db.commit()
    db.refresh(g)
    return _detail(g)


@router.delete("/{group_id}")
def delete_group(
    group_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)
):
    g = _group_or_404(db, group_id)
    if g.is_system_group:
        raise HTTPException(status_code=403, detail="System groups cannot be deleted")
    name = g.name
    db.delete(g)
    record(db, AuditAction.GROUP_DELETED, request, actor, group_id, "group", {"name": name})
    db.commit()
    return {"success": True}


def _sync_count(db: Session, g: Group) -> None:
    db.flush()
    db.expire(g, ["members"])
    g.member_count = len(g.members)


@router.post("/{group_id}/members", status_code=201)
def add_member(
    group_id: int,
    body: MemberAdd,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
):
    g = _group_or_404(db, group_id)
    user = db.get(User, body.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    exists = db.execute(
        user_group_association.select().where(
            user_group_association.c.group_id == g.id, user_group_association.c.user_id == user.id
        )
    ).first()
    if exists:
        raise HTTPException(status_code=409, detail="User is already a member")
    db.execute(
        insert(user_group_association).values(
            user_id=user.id, group_id=g.id, added_by_user_id=actor.id, added_at=datetime.now(timezone.utc)
        )
    )
    _sync_count(db, g)
    record(db, AuditAction.GROUP_MEMBER_ADDED, request, actor, g.id, "group", {"user_id": user.id})
    db.commit()
    db.refresh(g)
    return _detail(g)


@router.delete("/{group_id}/members/{user_id}")
def remove_member(
    group_id: int,
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
):
    g = _group_or_404(db, group_id)
    res = db.execute(
        delete(user_group_association).where(
            user_group_association.c.group_id == g.id, user_group_association.c.user_id == user_id
        )
    )
    if res.rowcount == 0:
        raise HTTPException(status_code=404, detail="Membership not found")
    _sync_count(db, g)
    record(db, AuditAction.GROUP_MEMBER_REMOVED, request, actor, g.id, "group", {"user_id": user_id})
    db.commit()
    db.refresh(g)
    return _detail(g)
