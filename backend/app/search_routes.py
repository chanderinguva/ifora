"""Global search for the admin command palette: users, groups, applications, recipes and group rules by name.

Read-only, admin-only, tenant-scoped by the session. Fixed small result sets; the query is bound (never interpolated)
and LIKE wildcards in it are escaped, so it matches literally.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from backend.app.auth.deps import require_admin
from backend.app.db import get_db
from backend.app.groups.model import Group
from backend.app.groups.rules import GroupRule
from backend.app.oidc.models import OIDCClient
from backend.app.recipes.models import Recipe
from backend.app.users.model import User

router = APIRouter(prefix="/admin", tags=["search"])
PER_KIND = 5


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


@router.get("/search")
def search(q: str = Query(..., min_length=2, max_length=100), db: Session = Depends(get_db), _: User = Depends(require_admin)):
    pat = _like(q.strip().lower())
    ci = lambda col: func.lower(col).like(pat, escape="\\")  # noqa: E731
    users = db.query(User).filter(or_(ci(User.email), ci(User.username), ci(User.first_name), ci(User.last_name),
                                      ci(func.concat(User.first_name, " ", User.last_name)))).order_by(User.id).limit(PER_KIND).all()
    groups = db.query(Group).filter(Group.is_system_group.is_(False), ci(Group.name)).order_by(Group.id).limit(PER_KIND).all()
    apps = db.query(OIDCClient).filter(or_(ci(OIDCClient.name), ci(OIDCClient.client_id))).order_by(OIDCClient.id).limit(PER_KIND).all()
    recipes = db.query(Recipe).filter(ci(Recipe.name)).order_by(Recipe.id).limit(PER_KIND).all()
    rules = db.query(GroupRule).filter(ci(GroupRule.name)).order_by(GroupRule.id).limit(PER_KIND).all()
    return {"results": (
        [{"kind": "user", "id": u.id, "title": f"{u.first_name} {u.last_name}".strip(), "subtitle": u.email, "href": f"/admin/users/{u.id}"} for u in users]
        + [{"kind": "group", "id": g.id, "title": g.name, "subtitle": f"{g.member_count} members", "href": f"/admin/groups/{g.id}"} for g in groups]
        + [{"kind": "application", "id": c.id, "title": c.name, "subtitle": c.client_type, "href": "/admin/oidc-clients"} for c in apps]
        + [{"kind": "recipe", "id": r.id, "title": r.name, "subtitle": "recipe", "href": f"/admin/recipes/{r.id}"} for r in recipes]
        + [{"kind": "group rule", "id": r.id, "title": r.name, "subtitle": r.status, "href": "/admin/group-rules"} for r in rules]
    )}
