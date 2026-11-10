"""Administrators list: everyone who can administer, with where each role comes from (ADR 024)."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.app.admin_roles.models import AdminRoleAssignment, GroupAdminRole
from backend.app.admin_roles.resolve import role_sources
from backend.app.api_tokens.models import ApiToken
from backend.app.auth.deps import require_admin
from backend.app.db import get_db
from backend.app.groups.model import user_group_association
from backend.app.users.model import User

router = APIRouter(prefix="/admin/administrators", tags=["administrators"])
MAX_ROWS = 500


@router.get("")
def list_administrators(role: str = Query("", max_length=32), mfa: str = Query("", max_length=8), q: str = Query("", max_length=100),
                        db: Session = Depends(get_db), _: User = Depends(require_admin)):
    direct = db.query(AdminRoleAssignment.user_id)
    via_group = db.query(user_group_association.c.user_id).join(GroupAdminRole, GroupAdminRole.group_id == user_group_association.c.group_id)
    query = db.query(User).filter(or_(User.is_admin.is_(True), User.id.in_(direct), User.id.in_(via_group)))
    if q.strip():
        like = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.filter(or_(User.email.ilike(like, escape="\\"), User.first_name.ilike(like, escape="\\"), User.last_name.ilike(like, escape="\\")))
    now = datetime.now(timezone.utc)
    items = []
    for u in query.order_by(User.last_name, User.first_name).limit(MAX_ROWS).all():
        sources = role_sources(db, u.id)
        if role and role not in sources and not (role == "super_admin" and u.is_super_admin):
            continue
        has_factor = u.has_second_factor
        if mfa == "none" and has_factor:
            continue
        tokens = db.query(ApiToken).filter(ApiToken.user_id == u.id, ApiToken.revoked_at.is_(None), ApiToken.expires_at > now).count()
        items.append({
            "id": u.id, "name": f"{u.first_name} {u.last_name}", "email": u.email, "status": u.status, "is_super_admin": u.is_super_admin,
            "roles": [{"role": r, "sources": s} for r, s in sorted(sources.items())], "mfa": has_factor,
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None, "active_api_tokens": tokens,
        })
    return {"items": items, "total": len(items)}
