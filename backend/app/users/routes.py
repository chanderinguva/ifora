"""Admin user management API (deny-by-default: every route requires an admin)."""

import re
import secrets
import string
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import insert, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.auth.deps import require_admin
from backend.app.auth.sessions_util import revoke_user_sessions
from backend.app.db import get_db
from backend.app.groups import rules as group_rules
from backend.app.groups.model import Group, user_group_association
from backend.app.profiles.schemas import validate_attributes, validate_password
from backend.app.users.model import User

router = APIRouter(prefix="/admin/users", tags=["users"])

_USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{1,49}$")


class UserCreate(BaseModel):
    email: EmailStr
    username: Optional[str] = None
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    password: Optional[str] = None
    generate_password: bool = False
    is_admin: bool = False
    profile_attributes: Dict[str, Any] = Field(default_factory=dict)
    group_ids: List[int] = Field(default_factory=list, max_length=20)

    @field_validator("password")
    @classmethod
    def _pw(cls, v):
        return validate_password(v) if v is not None else v

    @field_validator("username")
    @classmethod
    def _un(cls, v):
        if v is not None and not _USERNAME.match(v.lower()):
            raise ValueError("username must be 2-50 chars: letters, digits, . _ -")
        return v.lower() if v else v

    @field_validator("profile_attributes")
    @classmethod
    def _attrs(cls, v):
        return validate_attributes(v)


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    first_name: Optional[str] = Field(None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(None, min_length=1, max_length=100)
    status: Optional[str] = Field(None, pattern="^(active|inactive)$")
    is_admin: Optional[bool] = None
    profile_attributes: Optional[Dict[str, Any]] = None

    @field_validator("profile_attributes")
    @classmethod
    def _attrs(cls, v):
        return None if v is None else validate_attributes(v)


class PasswordReset(BaseModel):
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _pw(cls, v):
        return validate_password(v)


def _detail(user: User) -> dict:
    d = user.to_dict()
    d["groups"] = [{"id": g.id, "name": g.name} for g in user.groups]
    return d


def _get_or_404(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def _guard_target(actor: User, target: User) -> None:
    """Only super admins may modify other admins; nobody modifies a super admin here."""
    if target.is_super_admin and target.id != actor.id:
        raise HTTPException(status_code=403, detail="Cannot modify a super administrator")
    if target.is_admin and not actor.is_super_admin and target.id != actor.id:
        raise HTTPException(status_code=403, detail="Only a super administrator can modify administrators")


def _generate_password() -> str:
    """Random 20-char password that satisfies the password policy (mixed case + digit)."""
    alphabet = string.ascii_letters + string.digits
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(20))
        if any(c.islower() for c in pw) and any(c.isupper() for c in pw) and any(c.isdigit() for c in pw):
            return pw


def _unique_username(db: Session, base: str) -> str:
    base = re.sub(r"[^a-z0-9._-]", "", base.lower()) or "user"
    base = (base if len(base) >= 2 else base + "0")[:44]
    candidate, n = base, 1
    while db.query(User.id).filter(User.username == candidate).first():
        n += 1
        candidate = f"{base}{n}"
    return candidate


@router.get("")
def list_users(
    q: Optional[str] = Query(None, max_length=100),
    status: Optional[str] = Query(None, pattern="^(active|inactive)$"),
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    query = db.query(User)
    if q:
        like = f"%{q.lower().replace('%', '').replace('_', '')}%"
        from sqlalchemy import func

        query = query.filter(
            or_(
                func.lower(User.email).like(like),
                func.lower(User.username).like(like),
                func.lower(User.first_name).like(like),
                func.lower(User.last_name).like(like),
            )
        )
    if status:
        query = query.filter(User.status == status)
    total = query.count()
    items = query.order_by(User.id).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [u.to_dict() for u in items], "total": total, "page": page, "page_size": page_size}


@router.post("", status_code=201)
def create_user(
    body: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
):
    if body.is_admin and not actor.is_super_admin:
        raise HTTPException(status_code=403, detail="Only a super administrator can create administrators")
    if body.generate_password == (body.password is not None):
        raise HTTPException(status_code=422, detail="Provide a password, or ask for one to be generated (not both)")
    groups = []
    if body.group_ids:
        ids = sorted(set(body.group_ids))
        groups = db.query(Group).filter(Group.id.in_(ids)).all()
        if len(groups) != len(ids):
            raise HTTPException(status_code=422, detail="Unknown group")
        if any(g.is_system_group for g in groups):
            raise HTTPException(status_code=422, detail="System groups cannot be assigned here")
    password = body.password if body.password is not None else _generate_password()
    email = body.email.lower()
    if db.query(User.id).filter(User.email == email).first():
        raise HTTPException(status_code=409, detail="Email already in use")
    username = body.username or _unique_username(db, email.split("@")[0])
    if body.username and db.query(User.id).filter(User.username == username).first():
        raise HTTPException(status_code=409, detail="Username already in use")

    user = User(
        email=email,
        username=username,
        first_name=body.first_name,
        last_name=body.last_name,
        password=password,
        is_admin=body.is_admin,
    )
    user.set_profile_attributes(body.profile_attributes)
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="User already exists")
    record(db, AuditAction.USER_CREATED, request, actor, user.id, "user", {"email": email, "is_admin": body.is_admin})
    for g in groups:
        db.execute(insert(user_group_association).values(
            user_id=user.id, group_id=g.id, added_by_user_id=actor.id, added_at=datetime.now(timezone.utc)
        ))
        record(db, AuditAction.GROUP_MEMBER_ADDED, request, actor, g.id, "group", {"user_id": user.id})
        group_rules._recount(db, g.id)
    group_rules.evaluate_user(db, user, request, actor)
    db.commit()
    db.refresh(user)
    out = _detail(user)
    if body.generate_password:
        out["temporary_password"] = password  # shown once; only the hash is stored
    return out


@router.get("/{user_id}")
def get_user(user_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return _detail(_get_or_404(db, user_id))


@router.patch("/{user_id}")
def update_user(
    user_id: int,
    body: UserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
):
    user = _get_or_404(db, user_id)
    _guard_target(actor, user)
    changed: Dict[str, Any] = {}

    if body.email is not None and body.email.lower() != user.email:
        email = body.email.lower()
        if db.query(User.id).filter(User.email == email, User.id != user.id).first():
            raise HTTPException(status_code=409, detail="Email already in use")
        user.email = email
        changed["email"] = email
    if body.first_name is not None:
        user.first_name = body.first_name
        changed["first_name"] = True
    if body.last_name is not None:
        user.last_name = body.last_name
        changed["last_name"] = True
    if body.profile_attributes is not None:
        user.set_profile_attributes(body.profile_attributes)
        changed["profile_attributes"] = True

    if body.is_admin is not None and body.is_admin != user.is_admin:
        if not actor.is_super_admin:
            raise HTTPException(status_code=403, detail="Only a super administrator can change admin rights")
        if user.is_super_admin:
            raise HTTPException(status_code=403, detail="Cannot modify a super administrator")
        user.is_admin = body.is_admin
        changed["is_admin"] = body.is_admin

    deactivated = activated = False
    if body.status is not None and body.status != user.status:
        if user.id == actor.id and body.status != "active":
            raise HTTPException(status_code=400, detail="You cannot deactivate your own account")
        if user.is_super_admin and body.status != "active":
            raise HTTPException(status_code=403, detail="Cannot deactivate a super administrator")
        user.status = body.status
        changed["status"] = body.status
        deactivated, activated = body.status == "inactive", body.status == "active"

    if deactivated or "is_admin" in changed:
        revoke_user_sessions(db, user.id)  # force re-login with current rights
    if changed:
        db.flush()
        group_rules.evaluate_user(db, user, request, actor)  # attribute/status changes can move rule-based memberships

    if changed:
        action = AuditAction.USER_DEACTIVATED if deactivated else (
            AuditAction.USER_ACTIVATED if activated else AuditAction.USER_UPDATED
        )
        record(db, action, request, actor, user.id, "user", {"changed": changed})
    db.commit()
    db.refresh(user)
    return _detail(user)


@router.post("/{user_id}/password")
def reset_password(
    user_id: int,
    body: PasswordReset,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
):
    user = _get_or_404(db, user_id)
    _guard_target(actor, user)
    user.set_password(body.new_password)
    user.failed_login_attempts = 0
    user.lockout_until = None
    revoked = revoke_user_sessions(db, user.id)
    record(db, AuditAction.USER_PASSWORD_CHANGED, request, actor, user.id, "user", {"by": "admin", "sessions_revoked": revoked})
    db.commit()
    return {"success": True}


@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
):
    user = _get_or_404(db, user_id)
    if user.id == actor.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
    if user.is_super_admin:
        raise HTTPException(status_code=403, detail="Cannot delete a super administrator")
    _guard_target(actor, user)
    # added_by has no ON DELETE rule; detach before removing the row
    db.execute(
        update(user_group_association)
        .where(user_group_association.c.added_by_user_id == user.id)
        .values(added_by_user_id=None)
    )
    email = user.email
    db.delete(user)
    record(db, AuditAction.USER_DELETED, request, actor, user_id, "user", {"email": email})
    db.commit()
    return {"success": True}
