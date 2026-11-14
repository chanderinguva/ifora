"""Users as CSV: export, an import template, and import with a dry run (Okta-style bulk operations).

Import only creates users (existing ones are reported, never overwritten), never sets passwords or administrator rights, and
runs each row through the same code as the create-user API, so every rule (naming convention, reserved names, attribute types,
group guards, audit) applies. New accounts are invited by email, or left staged for an administrator to invite later.
"""

import hashlib
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from backend.app import mailer
from backend.app.audit.model import AuditAction, AuditEvent
from backend.app.audit.service import record
from backend.app.auth.deps import require_admin
from backend.app.config import settings
from backend.app.db import get_db
from backend.app.groups.model import Group, user_group_association
from backend.app.profiles import catalog as profile_catalog
from backend.app.users import csvio, lifecycle, naming
from backend.app.users.model import User
from backend.app.users.routes import UserCreate, _clean_attrs, create_user

router = APIRouter(prefix="/admin/users", tags=["users-csv"])
EXPORT_LIMIT = 50_000
SAMPLE = [
    {"username": "ada.lovelace", "email": "ada.lovelace@example.com", "first_name": "Ada", "last_name": "Lovelace", "user_type": "Employee",
     "department": "Engineering", "groups": "Team - Platform Engineering;Project - Migration 2027"},
    {"first_name": "Grace", "last_name": "Hopper", "user_type": "Contingent Worker", "department": "Research"},
]


def _attr_keys(db: Session) -> List[str]:
    return [a.key for a in profile_catalog.catalog(db) if a.key not in profile_catalog.RESERVED]


def _filename(kind: str) -> Dict[str, str]:
    return {"Content-Disposition": f'attachment; filename="{kind}.csv"', "Cache-Control": "no-store"}


@router.get("/export.csv")
def export_users(request: Request, q: Optional[str] = Query(None, max_length=100), status: Optional[str] = Query(None, pattern=lifecycle.STATUS_PATTERN),
                 db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    query = db.query(User)
    if q:
        like = f"%{q.lower().replace('%', '').replace('_', '')}%"
        query = query.filter(or_(func.lower(User.email).like(like), func.lower(User.username).like(like),
                                 func.lower(User.first_name).like(like), func.lower(User.last_name).like(like)))
    if status:
        query = query.filter(User.status == status)
    users = query.order_by(User.id).limit(EXPORT_LIMIT).all()
    names: Dict[int, List[str]] = {}
    if users:
        rows = (db.query(user_group_association.c.user_id, Group.name).join(Group, Group.id == user_group_association.c.group_id)
                .filter(user_group_association.c.user_id.in_([u.id for u in users])).order_by(Group.name))
        for uid, gname in rows:
            names.setdefault(uid, []).append(gname)
    keys = _attr_keys(db)
    headers = csvio.CORE + keys + [csvio.GROUPS] + csvio.READ_ONLY
    out = []
    for u in users:
        attrs = u.get_profile_attributes()
        out.append({"username": u.username, "email": u.email, "first_name": u.first_name, "last_name": u.last_name,
                    **{k: attrs.get(k) for k in keys}, csvio.GROUPS: ";".join(names.get(u.id, [])), "status": u.status, "id": u.id,
                    "last_login_at": u.last_login_at.isoformat() if u.last_login_at else "", "created_at": u.created_at.isoformat() if u.created_at else ""})
    record(db, AuditAction.USERS_EXPORTED, request, actor, None, "user", {"count": len(users), "q": q or "", "status": status or ""})
    db.commit()
    return Response(csvio.write(headers, out), media_type="text/csv; charset=utf-8", headers=_filename("users"))


@router.get("/import-template.csv")
def import_template(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    headers = csvio.CORE + _attr_keys(db) + [csvio.GROUPS]
    return Response(csvio.write(headers, SAMPLE), media_type="text/csv; charset=utf-8", headers=_filename("users-import-template"))


@router.get("/import-columns")
def import_columns(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """What each column means, for the import dialog."""
    cols = [
        {"name": "first_name", "required": True, "help": "Given name"}, {"name": "last_name", "required": True, "help": "Family name"},
        {"name": "username", "required": False, "help": "Leave empty to generate first.last (a number is added on a clash)"},
        {"name": "email", "required": False, "help": f"Leave empty to use username@{settings.PRIMARY_EMAIL_DOMAIN}" if settings.PRIMARY_EMAIL_DOMAIN else "Required: no primary email domain is configured"},
    ]
    cols += [{"name": a.key, "required": False, "help": a.display_name + (f" (one of: {', '.join(a.enum_options)})" if a.enum_options else "")}
             for a in profile_catalog.catalog(db) if a.key not in profile_catalog.RESERVED]
    cols.append({"name": "groups", "required": False, "help": "Existing group names separated by ;"})
    return {"columns": cols, "ignored_on_import": csvio.READ_ONLY, "max_rows": csvio.MAX_ROWS, "email_configured": mailer.configured()}


class ImportBody(BaseModel):
    csv: str = Field(..., max_length=csvio.MAX_BYTES)
    dry_run: bool = True
    send_invite: bool = False   # email each new user a set-password link; otherwise they are left staged
    allow_repeat: bool = False  # import a file that was already imported (otherwise refused, to stop double imports)


def _msgs(e: ValidationError) -> List[str]:
    return [f"{'.'.join(str(p) for p in x['loc']) or 'row'}: {x['msg'].removeprefix('Value error, ')}" for x in e.errors()]


def _plan(db: Session, row: Dict[str, str], keys: List[str], seen_email: set, seen_user: set, groups_by_name: Dict[str, Group]) -> Dict[str, Any]:
    errors: List[str] = []
    attrs = {k: row[k] for k in keys if row.get(k, "") != ""}
    group_ids: List[int] = []
    for name in [g.strip() for g in row.get(csvio.GROUPS, "").split(";") if g.strip()]:
        g = groups_by_name.get(name)
        if g is None:
            errors.append(f"groups: no group named '{name}'")
        elif g.is_system_group:
            errors.append(f"groups: '{name}' is a system group")
        else:
            group_ids.append(g.id)
    try:
        body = UserCreate(email=row.get("email") or None, username=row.get("username") or None, first_name=row.get("first_name", ""),
                          last_name=row.get("last_name", ""), generate_password=True, profile_attributes=attrs, group_ids=group_ids)
    except ValidationError as e:
        errors += _msgs(e)
        body = None
    if body is not None:
        try:
            _clean_attrs(db, {"user_type": profile_catalog.DEFAULT_USER_TYPE, **body.profile_attributes}, {})
        except HTTPException as e:
            errors.append(str(e.detail))
        if body.username and body.username in naming.RESERVED:
            errors.append("username: reserved")
        if body.email is None and not settings.PRIMARY_EMAIL_DOMAIN:
            errors.append("email: required (no primary email domain is configured)")
        if body.email is not None:
            em = str(body.email).lower()
            if em in seen_email:
                errors.append("email: repeated in this file")
            elif db.query(User.id).filter(func.lower(User.email) == em).first():
                errors.append("email: already in use (existing users are not changed by import)")
            seen_email.add(em)
        if body.username:
            if body.username in seen_user:
                errors.append("username: repeated in this file")
            elif db.query(User.id).filter(func.lower(User.username) == body.username).first():
                errors.append("username: already in use (existing users are not changed by import)")
            seen_user.add(body.username)
    return {"ok": not errors, "errors": errors, "body": body}


@router.post("/import")
def import_users(body: ImportBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    try:
        headers, rows = csvio.read(body.csv)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    keys = _attr_keys(db)
    known = set(csvio.CORE) | set(keys) | {csvio.GROUPS} | set(csvio.READ_ONLY)
    if {"password", "is_admin", "is_super_admin"} & set(headers):
        raise HTTPException(status_code=422, detail="Import cannot set passwords or administrator rights; remove those columns")
    unknown = [h for h in headers if h not in known]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown column(s): {', '.join(unknown)}. Define attributes in the Profile editor first, or download the template.")
    missing = [c for c in ("first_name", "last_name") if c not in headers]
    if missing:
        raise HTTPException(status_code=422, detail=f"Missing required column(s): {', '.join(missing)}")
    if not rows:
        raise HTTPException(status_code=422, detail="The file has no data rows")
    digest = hashlib.sha256(body.csv.encode()).hexdigest()
    if not body.dry_run:
        if body.send_invite and not mailer.configured():
            raise HTTPException(status_code=409, detail="Email is not configured on this server, so invitations cannot be sent")
        if not body.allow_repeat and db.query(AuditEvent.id).filter(AuditEvent.action == AuditAction.USERS_IMPORTED.value,
                                                                     AuditEvent.event_metadata["sha256"].astext == digest).first():
            raise HTTPException(status_code=409, detail="This exact file was already imported. Importing it again would create duplicates for rows without a username or email.")
    groups_by_name = {g.name: g for g in db.query(Group).all()}
    seen_email: set = set()
    seen_user: set = set()
    plans = [(r, _plan(db, r, keys, seen_email, seen_user, groups_by_name)) for r in rows]
    results: List[Dict[str, Any]] = []
    created = 0
    for row, plan in plans:
        item = {"line": row["_line"], "email": row.get("email", ""), "username": row.get("username", ""), "name": f"{row.get('first_name', '')} {row.get('last_name', '')}".strip(),
                "ok": plan["ok"], "errors": plan["errors"], "created": False}
        if plan["ok"] and not body.dry_run:
            b: UserCreate = plan["body"]
            b.send_invite, b.generate_password = body.send_invite, not body.send_invite
            try:
                out = create_user(b, request, db, actor)
                item.update(created=True, username=out["username"], email=out["email"])
                created += 1
                if not body.send_invite:
                    u = db.get(User, out["id"])
                    u.status = "staged"     # no usable password exists; an administrator invites them later
                    db.commit()
            except HTTPException as e:
                db.rollback()
                item.update(ok=False, errors=[str(e.detail)])
        results.append(item)
    valid = sum(1 for r in results if r["ok"])
    if not body.dry_run:
        record(db, AuditAction.USERS_IMPORTED, request, actor, None, "user",
               {"sha256": digest, "rows": len(results), "created": created, "failed": len(results) - created, "invited": body.send_invite})
        db.commit()
    return {"dry_run": body.dry_run, "total": len(results), "valid": valid, "invalid": len(results) - valid, "created": created, "results": results,
            "outcome": "staged" if not body.send_invite else "invited"}
