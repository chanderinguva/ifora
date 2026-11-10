"""Admin group management API."""

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, insert
from sqlalchemy.orm import Session, object_session

from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.auth.deps import require_admin
from backend.app.db import get_db
from backend.app.admin_roles import resolve as role_resolve
from backend.app.groups import standards
from backend.app.groups.model import Group, user_group_association
from backend.app.listing import ListParams, list_params, paginate, sortable
from backend.app.scim import filter as flt
from backend.app.users.model import User

router = APIRouter(prefix="/admin/groups", tags=["groups"])

# filterable / sortable attributes of GET /admin/groups: the response field names (lower case)
GROUP_LIST_ATTRS = {
    "name": flt.Attr("str", Group.name), "description": flt.Attr("str", Group.description),
    "type": flt.Attr("str", Group.type), "sensitivity": flt.Attr("str", Group.sensitivity),
    "is_system_group": flt.Attr("bool", Group.is_system_group),
    "created_at": flt.Attr("date", Group.created_at), "updated_at": flt.Attr("date", Group.updated_at),
}
GROUP_SORT = sortable(GROUP_LIST_ATTRS, id=Group.id, member_count=Group.member_count, review_by=Group.review_by)


class GroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    type: str = "other"
    owner_user_id: Optional[int] = None
    sensitivity: Optional[str] = None
    review_by: Optional[date] = None
    tags: List[str] = Field(default_factory=list)
    attributes: Dict[str, Any] = Field(default_factory=dict)


class GroupUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    type: Optional[str] = None
    owner_user_id: Optional[int] = None
    sensitivity: Optional[str] = None
    review_by: Optional[date] = None
    tags: Optional[List[str]] = None
    attributes: Optional[Dict[str, Any]] = None


class MemberAdd(BaseModel):
    user_id: int


def _group_or_404(db: Session, group_id: int) -> Group:
    g = db.get(Group, group_id)
    if g is None:
        raise HTTPException(status_code=404, detail="Group not found")
    return g


def _detail(g: Group) -> dict:
    d = g.to_dict()
    via = {}
    if g.members:
        from sqlalchemy import select as _select

        via = dict(
            object_session(g).execute(
                _select(user_group_association.c.user_id, user_group_association.c.rule_id).where(
                    user_group_association.c.group_id == g.id
                )
            ).all()
        )
    d["members"] = [
        {"id": u.id, "email": u.email, "first_name": u.first_name, "last_name": u.last_name, "via_rule": via.get(u.id)}
        for u in sorted(g.members, key=lambda u: u.id)
    ]
    return d


def _name_taken(db: Session, name: str, exclude_id: Optional[int] = None) -> bool:
    q = db.query(Group.id).filter(func.lower(Group.name) == name.lower())
    if exclude_id is not None:
        q = q.filter(Group.id != exclude_id)
    return q.first() is not None


def _check_meta(db: Session, type_: str, owner_user_id: Optional[int], sensitivity: Optional[str]) -> None:
    if type_ not in standards.TYPES:
        raise HTTPException(status_code=422, detail="Unknown group type")
    if sensitivity is not None and sensitivity not in standards.SENSITIVITY:
        raise HTTPException(status_code=422, detail="Sensitivity must be low, medium or high")
    if owner_user_id is not None and db.get(User, owner_user_id) is None:
        raise HTTPException(status_code=422, detail="Unknown owner")


@router.get("/standards")
def group_standards(_: User = Depends(require_admin)):
    """The group types and metadata rules, in a form scripts and AI assistants can read."""
    return standards.document()


@router.get("/analytics")
def group_analytics(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Directory-wide group health: composition by type, ownership gaps, empty and overdue groups."""
    from backend.app.admin_roles.models import GroupAdminRole

    groups = db.query(Group).filter(Group.is_system_group.is_(False)).all()
    today = date.today()
    needs_owner = {k for k, v in standards.TYPES.items() if "owner" in v["requires"]}
    by_type = {k: 0 for k in standards.TYPE_IDS}
    by_sens = {"low": 0, "medium": 0, "high": 0, "unset": 0}
    for g in groups:
        by_type[g.type if g.type in by_type else "other"] += 1
        by_sens[g.sensitivity or "unset"] += 1
    role_groups = {gid for (gid,) in db.query(GroupAdminRole.group_id).distinct()}
    brief = lambda g: {"id": g.id, "name": g.name, "type": g.type, "member_count": g.member_count}  # noqa: E731
    return {
        "total": len(groups),
        "by_type": by_type,
        "by_sensitivity": by_sens,
        "unclassified": by_type["other"],
        "without_owner": [brief(g) for g in groups if g.type in needs_owner and g.owner_user_id is None][:20],
        "without_owner_count": sum(1 for g in groups if g.type in needs_owner and g.owner_user_id is None),
        "empty": sum(1 for g in groups if g.member_count == 0),
        "review_overdue": [brief(g) for g in groups if g.review_by and g.review_by < today][:20],
        "review_overdue_count": sum(1 for g in groups if g.review_by and g.review_by < today),
        "with_admin_roles": len(role_groups),
        "largest": [brief(g) for g in sorted(groups, key=lambda g: -g.member_count)[:5]],
    }


@router.get("")
def list_groups(
    type: Optional[str] = Query(None, max_length=20),
    owner_user_id: Optional[int] = Query(None),
    ownerless: bool = Query(False),
    sensitivity: Optional[str] = Query(None, max_length=8),
    tag: Optional[str] = Query(None, max_length=30),
    q: Optional[str] = Query(None, max_length=100),
    p: ListParams = Depends(list_params),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    query = db.query(Group)
    if type:
        query = query.filter(Group.type == type)
    if owner_user_id is not None:
        query = query.filter(Group.owner_user_id == owner_user_id)
    if ownerless:
        query = query.filter(Group.owner_user_id.is_(None), Group.is_system_group.is_(False))
    if sensitivity:
        query = query.filter(Group.sensitivity == sensitivity)
    if tag:
        query = query.filter(Group.tags.contains([tag.lower()]))
    if q:
        query = query.filter(func.lower(Group.name).like(f"%{q.lower().replace('%', '').replace('_', '')}%"))
    return paginate(query, p, sort=GROUP_SORT, default_order=[Group.id], tiebreak=Group.id, filter_attrs=GROUP_LIST_ATTRS,
                    render=lambda rows: [g.to_dict() for g in rows])


@router.post("", status_code=201)
def create_group(
    body: GroupCreate, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)
):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Name is required")
    if _name_taken(db, name):
        raise HTTPException(status_code=409, detail="Group name already in use")
    _check_meta(db, body.type, body.owner_user_id, body.sensitivity)
    standards.check_requirements(body.type, body.owner_user_id, body.review_by)
    g = Group(name=name, description=body.description, group_type=body.type)
    g.owner_user_id, g.sensitivity, g.review_by = body.owner_user_id, body.sensitivity, body.review_by
    g.tags = standards.clean_tags(body.tags)
    g.set_attributes(standards.clean_attributes(body.attributes))
    db.add(g)
    db.flush()
    record(db, AuditAction.GROUP_CREATED, request, actor, g.id, "group", {"name": name, "type": body.type})
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
    sent = body.model_fields_set
    meta = sent & {"type", "owner_user_id", "sensitivity", "review_by"}
    if meta:
        new_type = body.type if "type" in sent and body.type is not None else g.type
        owner = body.owner_user_id if "owner_user_id" in sent else g.owner_user_id
        review = body.review_by if "review_by" in sent else g.review_by
        sens = body.sensitivity if "sensitivity" in sent else g.sensitivity
        _check_meta(db, new_type, owner, sens)
        standards.check_requirements(new_type, owner, review)
        if new_type != g.type and role_resolve.group_has_roles(db, g.id) and not standards.TYPES[new_type]["can_carry_admin_roles"]:
            raise HTTPException(status_code=409, detail="This group carries administrator roles; remove them before changing its type")
        for field, new in (("type", new_type), ("owner_user_id", owner), ("sensitivity", sens), ("review_by", review)):
            if getattr(g, field) != new:
                setattr(g, field, new)
                changed[field] = str(new) if new is not None else None
    if body.tags is not None:
        g.tags = standards.clean_tags(body.tags)
        changed["tags"] = True
    if body.attributes is not None:
        g.set_attributes(standards.clean_attributes(body.attributes))
        changed["attributes"] = True
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
    role_resolve.guard_role_groups(db, [g.id], actor)
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
    if g.is_system_group:
        raise HTTPException(status_code=403, detail="System groups cannot be modified")
    role_resolve.guard_role_groups(db, [g.id], actor)
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
    if g.is_system_group:
        raise HTTPException(status_code=403, detail="System groups cannot be modified")
    role_resolve.guard_role_groups(db, [g.id], actor)
    managed = db.execute(
        user_group_association.select().where(
            user_group_association.c.group_id == g.id,
            user_group_association.c.user_id == user_id,
            user_group_association.c.rule_id.is_not(None),
        )
    ).first()
    if managed:
        raise HTTPException(status_code=409, detail="This membership is managed by a group rule; change or deactivate the rule instead")
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
