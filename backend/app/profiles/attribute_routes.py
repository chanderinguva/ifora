"""Admin API for the Profile editor (attribute catalog)."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.auth.deps import require_admin
from backend.app.db import get_db
from backend.app.groups.rules import GroupRule
from backend.app.profiles import catalog as cat
from backend.app.users.model import User

router = APIRouter(prefix="/admin/profile-attributes", tags=["profile-editor"])


class AttrCreate(BaseModel):
    key: str = Field(..., max_length=50)
    display_name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    data_type: str = "string"
    enum_options: Optional[List[str]] = None
    user_editable: bool = False


class AttrUpdate(BaseModel):
    display_name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    enum_options: Optional[List[str]] = None
    user_editable: Optional[bool] = None


def _options(opts: Optional[List[str]]) -> List[str]:
    clean = [o.strip() for o in (opts or []) if o and o.strip()]
    if not clean or len(clean) > 50 or len(set(clean)) != len(clean) or any(len(o) > 100 for o in clean):
        raise HTTPException(status_code=422, detail="An enum needs 1-50 distinct options of up to 100 characters")
    return clean


def _rules_using(db: Session, key: str) -> List[str]:
    return [r.name for r in db.query(GroupRule).all() if any(c.get("attribute") == key for c in r.conditions)]


def _get(db: Session, key: str) -> cat.ProfileAttribute:
    a = cat.by_key(db).get(key)
    if a is None:
        raise HTTPException(status_code=404, detail="Attribute not found")
    return a


@router.get("")
def list_attributes(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return {"items": [a.to_dict() for a in cat.catalog(db)], "data_types": list(cat.DATA_TYPES)}


@router.post("", status_code=201)
def create_attribute(body: AttrCreate, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    key = body.key.strip().lower()
    if not cat.KEY_RE.match(key):
        raise HTTPException(status_code=422, detail="Key must be lowercase letters, digits and underscores, starting with a letter")
    if key in cat.RESERVED:
        raise HTTPException(status_code=422, detail=f"'{key}' is reserved")
    if body.data_type not in ("string", "number", "boolean", "enum"):
        raise HTTPException(status_code=422, detail="Custom attributes can be string, number, boolean or enum")
    existing = cat.catalog(db)
    if len(existing) >= cat.MAX_ATTRIBUTES:
        raise HTTPException(status_code=409, detail=f"At most {cat.MAX_ATTRIBUTES} attributes")
    attr = cat.ProfileAttribute(
        key=key, display_name=body.display_name.strip(), description=body.description, data_type=body.data_type,
        enum_options=_options(body.enum_options) if body.data_type == "enum" else None,
        user_editable=body.user_editable, built_in=False, sort_order=len(existing),
    )
    db.add(attr)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="An attribute with this key already exists")
    record(db, AuditAction.PROFILE_ATTRIBUTE_CREATED, request, actor, attr.id, "profile_attribute",
           {"key": key, "type": attr.data_type, "user_editable": attr.user_editable})
    db.commit()
    return attr.to_dict()


@router.patch("/{key}")
def update_attribute(key: str, body: AttrUpdate, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    a = _get(db, key)
    changed = {}
    if body.display_name is not None:
        a.display_name = body.display_name.strip(); changed["display_name"] = True
    if body.description is not None:
        a.description = body.description; changed["description"] = True
    if body.enum_options is not None:
        if a.data_type != "enum":
            raise HTTPException(status_code=422, detail="Only enum attributes have options")
        a.enum_options = _options(body.enum_options); changed["enum_options"] = True
    if body.user_editable is not None and body.user_editable != a.user_editable:
        if body.user_editable:
            used = _rules_using(db, a.key)
            if used:
                # otherwise users could edit their way into the groups these rules populate
                raise HTTPException(status_code=409, detail=f"Used by group rule(s): {', '.join(used)}. Remove those conditions first.")
        a.user_editable = body.user_editable
        changed["user_editable"] = body.user_editable
    if changed:
        record(db, AuditAction.PROFILE_ATTRIBUTE_UPDATED, request, actor, a.id, "profile_attribute", {"key": a.key, "changed": changed})
    db.commit()
    return a.to_dict()


@router.delete("/{key}")
def delete_attribute(key: str, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    a = _get(db, key)
    if a.built_in:
        raise HTTPException(status_code=403, detail="Built-in attributes cannot be deleted")
    used = _rules_using(db, a.key)
    if used:
        raise HTTPException(status_code=409, detail=f"Used by group rule(s): {', '.join(used)}")
    stripped = 0
    for u in db.query(User).all():  # values are dropped with the definition (Okta behaviour)
        attrs = u.get_profile_attributes()
        if a.key in attrs:
            del attrs[a.key]
            u.set_profile_attributes(attrs)
            stripped += 1
    db.delete(a)
    record(db, AuditAction.PROFILE_ATTRIBUTE_DELETED, request, actor, a.id, "profile_attribute", {"key": a.key, "users_cleared": stripped})
    db.commit()
    return {"success": True, "users_cleared": stripped}
