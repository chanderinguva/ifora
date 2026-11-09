"""A user's effective administrator roles: the ones assigned to them directly plus the ones carried by their groups (ADR 019)."""

from collections import defaultdict
from typing import Dict, List

from sqlalchemy.orm import Session

from backend.app.admin_roles.models import AdminRoleAssignment, GroupAdminRole
from backend.app.groups.model import Group, user_group_association


def role_sources(db: Session, user_id: int) -> Dict[str, List[dict]]:
    """role -> where it comes from: {"via": "direct"} or {"via": "group", "group_id", "group_name"}."""
    out: Dict[str, List[dict]] = defaultdict(list)
    for (r,) in db.query(AdminRoleAssignment.role).filter(AdminRoleAssignment.user_id == user_id):
        out[r].append({"via": "direct"})
    rows = (
        db.query(GroupAdminRole.role, Group.id, Group.name)
        .join(Group, Group.id == GroupAdminRole.group_id)
        .join(user_group_association, user_group_association.c.group_id == Group.id)
        .filter(user_group_association.c.user_id == user_id)
    )
    for role, gid, gname in rows:
        out[role].append({"via": "group", "group_id": gid, "group_name": gname})
    return dict(out)


def roles_of(db: Session, user_id: int) -> List[str]:
    return sorted(role_sources(db, user_id))


def direct_roles(db: Session, user_id: int) -> List[str]:
    return sorted(r for (r,) in db.query(AdminRoleAssignment.role).filter(AdminRoleAssignment.user_id == user_id))


def group_has_roles(db: Session, group_id: int) -> bool:
    return db.query(GroupAdminRole.id).filter(GroupAdminRole.group_id == group_id).first() is not None


def role_group_ids(db: Session, group_ids) -> List[int]:
    ids = list(group_ids)
    if not ids:
        return []
    return [g for (g,) in db.query(GroupAdminRole.group_id).filter(GroupAdminRole.group_id.in_(ids)).distinct()]


def guard_role_groups(db: Session, group_ids, actor) -> None:
    """Joining a group that carries administrator roles is a privilege grant, so only a super administrator may change it."""
    from fastapi import HTTPException

    if not actor.is_super_admin and role_group_ids(db, group_ids):
        raise HTTPException(status_code=403, detail="This group carries administrator roles; only a super administrator can change who is in it")
