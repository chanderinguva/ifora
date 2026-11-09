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
from backend.app import mailer
from backend.app.auth import password_tokens, recovery_routes
from backend.app.users import lifecycle
from backend.app.db import get_db
from backend.app.groups import rules as group_rules
from backend.app.groups.model import Group, user_group_association
from backend.app.profiles import catalog as profile_catalog
from backend.app.recipes import events as recipe_events
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
    send_invite: bool = False  # email a one-time set-password link; the account starts as "provisioned"

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
    status: Optional[str] = Field(None, pattern=lifecycle.STATUS_PATTERN)
    is_admin: Optional[bool] = None
    profile_attributes: Optional[Dict[str, Any]] = None

    @field_validator("profile_attributes")
    @classmethod
    def _attrs(cls, v):
        return None if v is None else validate_attributes(v)


class PasswordReset(BaseModel):
    new_password: str
    require_change: bool = False  # Okta PASSWORD_EXPIRED: the user must choose their own password at next sign-in

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


def _clean_attrs(db: Session, values: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    """Admins may set any attribute defined in the Profile editor; values are type-checked."""
    try:
        cleaned = profile_catalog.validate_values(db, values, only_editable_by_user=False, current=current)
    except profile_catalog.PermissionError_ as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    except profile_catalog.AttributeError_ as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {k: v for k, v in cleaned.items() if v is not None}


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
    status: Optional[str] = Query(None, pattern=lifecycle.STATUS_PATTERN),
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
    if body.send_invite:
        if body.password is not None:
            raise HTTPException(status_code=422, detail="An invited user chooses their own password; do not set one")
        if not mailer.configured():
            raise HTTPException(status_code=409, detail="Email is not configured on this server (SMTP_HOST / SMTP_FROM)")
        body.generate_password = True  # unknown placeholder; the invitation link is the only way in
    elif body.generate_password == (body.password is not None):
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
    user.set_profile_attributes(_clean_attrs(db, body.profile_attributes, {}))
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
    invited = None
    if body.send_invite:
        user.status = "provisioned"
        raw = password_tokens.issue(db, user, "invite")
        record(db, AuditAction.USER_INVITED, request, actor, user.id, "user", {})
    group_rules.evaluate_user(db, user, request, actor)
    db.commit()
    db.refresh(user)
    if body.send_invite:
        invited = recovery_routes.send_link(user, "invite", raw, db)
    out = _detail(user)
    if invited is not None:
        out["invitation_sent"] = invited
    if body.generate_password and not body.send_invite:
        out["temporary_password"] = password  # shown once; only the hash is stored
    return out


class BulkBody(BaseModel):
    user_ids: List[int] = Field(..., min_length=1, max_length=100)
    action: str = Field(..., pattern="^(activate|suspend|unsuspend|deactivate|unlock)$")


# action -> (new status, statuses it may start from)
_BULK = {
    "activate": ("active", {"staged", "provisioned", "deprovisioned"}),
    "suspend": ("suspended", {"active"}),
    "unsuspend": ("active", {"suspended"}),
    "unlock": ("active", {"locked_out"}),
    "deactivate": ("deprovisioned", {"staged", "provisioned", "active", "recovery", "password_expired", "locked_out", "suspended"}),
}


@router.post("/bulk")
def bulk_action(body: BulkBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    """Apply one lifecycle action to many users. Each user is checked on its own; refusals are reported, not raised."""
    new, allowed = _BULK[body.action]
    results = []
    for uid in dict.fromkeys(body.user_ids):
        u = db.query(User).filter(User.id == uid).first()
        reason = None
        if u is None:
            reason = "not found"
        elif u.id == actor.id:
            reason = "you cannot change your own account"
        elif u.is_super_admin:
            reason = "super administrators are protected"
        elif u.is_admin and not actor.is_super_admin:
            reason = "only a super administrator can modify administrators"
        elif u.status not in allowed:
            reason = f"not allowed from status '{u.status}'"
        if reason:
            results.append({"user_id": uid, "ok": False, "reason": reason})
            continue
        lifecycle.set_status(db, u, new, request, actor)
        results.append({"user_id": uid, "ok": True, "status": u.status})
    db.commit()
    return {"action": body.action, "done": sum(1 for r in results if r["ok"]), "results": results}



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
        old_attrs = dict(user.get_profile_attributes())
        user.set_profile_attributes(_clean_attrs(db, body.profile_attributes, user.get_profile_attributes()))
        changed["profile_attributes"] = True
        recipe_events.emit_attribute_changes(db, user, old_attrs, user.get_profile_attributes(), actor)

    if body.is_admin is not None and body.is_admin != user.is_admin:
        if not actor.is_super_admin:
            raise HTTPException(status_code=403, detail="Only a super administrator can change admin rights")
        if user.is_super_admin:
            raise HTTPException(status_code=403, detail="Cannot modify a super administrator")
        user.is_admin = body.is_admin
        changed["is_admin"] = body.is_admin

    status_result = None
    if body.status is not None and lifecycle.normalize(body.status) != user.status:
        if user.id == actor.id and body.status != "active":
            raise HTTPException(status_code=400, detail="You cannot change your own account status")
        if user.is_super_admin and body.status != "active":
            raise HTTPException(status_code=403, detail="Cannot change the status of a super administrator")
        changed["status"] = lifecycle.normalize(body.status)

    if "is_admin" in changed:
        revoke_user_sessions(db, user.id)  # force re-login with current rights
    if changed:
        db.flush()
        if "status" in changed:
            status_result = lifecycle.set_status(db, user, changed["status"], request, actor)  # sessions, groups, audit
        else:
            group_rules.evaluate_user(db, user, request, actor)  # attribute changes can move rule-based memberships

    if changed and set(changed) != {"status"}:
        rest = {k: v for k, v in changed.items() if k != "status"}
        record(db, AuditAction.USER_UPDATED, request, actor, user.id, "user", {"changed": rest})
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
    if body.require_change and user.status == "active":
        user.status = "password_expired"
    record(db, AuditAction.USER_PASSWORD_CHANGED, request, actor, user.id, "user",
           {"by": "admin", "sessions_revoked": revoked, "require_change": body.require_change})
    db.commit()
    return {"success": True}


@router.post("/{user_id}/send-invite")
def send_invite(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
):
    """(Re)send the set-password email. Moves a staged account to provisioned. Not for active accounts."""
    user = _get_or_404(db, user_id)
    _guard_target(actor, user)
    if user.status not in ("staged", "provisioned"):
        raise HTTPException(status_code=409, detail="Only staged or provisioned accounts can be invited")
    if not mailer.configured():
        raise HTTPException(status_code=409, detail="Email is not configured on this server (SMTP_HOST / SMTP_FROM)")
    user.status = "provisioned"
    raw = password_tokens.issue(db, user, "invite")
    record(db, AuditAction.USER_INVITED, request, actor, user.id, "user", {"resend": True})
    db.commit()
    if not recovery_routes.send_link(user, "invite", raw, db):
        raise HTTPException(status_code=502, detail="The mail server did not accept the message")
    return {"success": True}


@router.post("/{user_id}/send-reset")
def send_reset(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
):
    """Email the user a password-reset link (the admin never sees or sets the password)."""
    user = _get_or_404(db, user_id)
    _guard_target(actor, user)
    if user.status not in recovery_routes.RESETTABLE:
        raise HTTPException(status_code=409, detail="This account's status does not allow a password reset")
    if not mailer.configured():
        raise HTTPException(status_code=409, detail="Email is not configured on this server (SMTP_HOST / SMTP_FROM)")
    raw = password_tokens.issue(db, user, "reset")
    record(db, AuditAction.PASSWORD_RESET_REQUESTED, request, actor, user.id, "user", {"by": "admin"})
    db.commit()
    if not recovery_routes.send_link(user, "reset", raw, db):
        raise HTTPException(status_code=502, detail="The mail server did not accept the message")
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


@router.get("/{user_id}/applications")
def user_applications(user_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Applications this user may use, and whether that comes from a direct assignment or a group."""
    from backend.app.applications.models import Application, ApplicationAssignment

    _get_or_404(db, user_id)
    direct = {a for (a,) in db.query(ApplicationAssignment.application_id).filter(ApplicationAssignment.user_id == user_id)}
    gids = [g for (g,) in db.execute(user_group_association.select().with_only_columns(user_group_association.c.group_id).where(user_group_association.c.user_id == user_id)).all()]
    via_group: Dict[int, List[str]] = {}
    if gids:
        rows = (db.query(ApplicationAssignment.application_id, Group.name)
                .join(Group, Group.id == ApplicationAssignment.group_id).filter(ApplicationAssignment.group_id.in_(gids)).all())
        for app_id, gname in rows:
            via_group.setdefault(app_id, []).append(gname)
    ids = direct | set(via_group)
    apps = db.query(Application).filter(Application.id.in_(ids)).order_by(Application.name).all() if ids else []
    return {"items": [{"id": a.id, "name": a.name, "sign_on_mode": a.sign_on_mode, "status": a.status,
                       "direct": a.id in direct, "groups": sorted(via_group.get(a.id, []))} for a in apps]}


@router.get("/{user_id}/events")
def user_events(user_id: int, page_size: int = Query(25, ge=1, le=100), db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Audit events about this user (as the target) or performed by them (as the actor)."""
    from backend.app.audit.model import AuditEvent

    _get_or_404(db, user_id)
    rows = (db.query(AuditEvent)
            .filter(or_((AuditEvent.target_type == "user") & (AuditEvent.target_id == str(user_id)), AuditEvent.actor_id == str(user_id)))
            .order_by(AuditEvent.timestamp.desc(), AuditEvent.id.desc()).limit(page_size).all())
    return {"items": [e.to_dict() for e in rows]}
