"""Secure Web Authentication endpoints (ADR 012).

The user stores their account for a legacy application once (password encrypted at rest). Launching a tile opens the UI page
/swa/continue, which asks `POST /api/v1/swa/apps/{id}/launch` for the form fields and auto-posts them (POST, never a URL)
to the login URL an administrator registered. A credential is only released to the signed-in, entitled user, who must have
signed in recently; no endpoint ever returns a stored password except that one, and administrators can only reset or list.
"""

import re
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app import ratelimit
from backend.app.applications import entitlement as ent
from backend.app.applications.models import Application
from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.auth.deps import get_session_and_user, require_admin
from backend.app.config import settings
from backend.app.db import get_db
from backend.app.swa import vault
from backend.app.swa.models import SwaConfig, SwaCredential
from backend.app.users.model import User

admin_router = APIRouter(prefix="/admin/applications", tags=["swa"])
api_router = APIRouter(prefix="/swa", tags=["swa"])
NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}

_FIELD = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-\[\]:]{0,63}$")
_LOOPBACK = {"localhost", "127.0.0.1", "::1"}
MAX_EXTRA = 10
SOURCES = ("user", "email", "username")


def _login_url(v: str) -> str:
    v = v.strip()
    u = urlsplit(v)
    try:
        host = u.hostname
    except ValueError:
        host = None
    ok_scheme = u.scheme == "https" or (u.scheme == "http" and host in _LOOPBACK)
    if not ok_scheme or not host or u.username or u.password or u.fragment:
        raise HTTPException(status_code=422, detail="The login URL must be https (http only for localhost) without credentials or a fragment")
    return v


class ExtraField(BaseModel):
    name: str = Field(..., max_length=64)
    value: str = Field("", max_length=500)


class SwaBody(BaseModel):
    login_url: str = Field(..., min_length=1, max_length=2000)
    username_field: str = Field(..., max_length=64)
    password_field: str = Field(..., max_length=64)
    extra_fields: List[ExtraField] = Field(default_factory=list, max_length=MAX_EXTRA)
    username_source: str = Field("user", pattern="^(" + "|".join(SOURCES) + ")$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _cfg_dict(c: SwaConfig) -> dict:
    return {"login_url": c.login_url, "username_field": c.username_field, "password_field": c.password_field,
            "extra_fields": c.extra_fields or [], "username_source": c.username_source}


def _swa_app(db: Session, app_id: int) -> Application:
    a = db.get(Application, app_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return a


# ---- admin ---------------------------------------------------------------------------------------------------------

@admin_router.get("/{app_id}/swa")
def get_config(app_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    a = _swa_app(db, app_id)
    c = db.query(SwaConfig).filter(SwaConfig.application_id == a.id).first()
    n = db.query(SwaCredential.id).filter(SwaCredential.application_id == a.id).count()
    return {"config": _cfg_dict(c) if c else None, "vault_enabled": vault.available(), "credentials": n}


@admin_router.put("/{app_id}/swa")
def put_config(app_id: int, body: SwaBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    a = _swa_app(db, app_id)
    if a.sign_on_mode != "swa":
        raise HTTPException(status_code=409, detail="Set the application's sign-on mode to Secure Web Authentication first")
    url = _login_url(body.login_url)
    uf, pf = body.username_field.strip(), body.password_field.strip()
    if not _FIELD.match(uf) or not _FIELD.match(pf) or uf == pf:
        raise HTTPException(status_code=422, detail="Field names must be plain form field names, and the username and password fields must differ")
    extras, seen = [], {uf, pf}
    for f in body.extra_fields:
        n = f.name.strip()
        if not _FIELD.match(n) or n in seen:
            raise HTTPException(status_code=422, detail=f"Extra field '{n[:30]}' is not a valid, unique field name")
        seen.add(n)
        extras.append({"name": n, "value": f.value})
    c = db.query(SwaConfig).filter(SwaConfig.application_id == a.id).first()
    if c is None:
        c = SwaConfig(application_id=a.id)
        db.add(c)
    changed_target = c.login_url is not None and c.login_url != url
    c.login_url, c.username_field, c.password_field, c.extra_fields, c.username_source, c.updated_at = url, uf, pf, extras, body.username_source, _now()
    if changed_target:
        # Stored passwords were given for the old destination: they must not be sent somewhere else without the user's say-so.
        db.query(SwaCredential).filter(SwaCredential.application_id == a.id).delete()
    record(db, AuditAction.APPLICATION_SWA_UPDATED, request, actor, a.id, "application",
           {"name": a.name, "login_url": url, "credentials_cleared": bool(changed_target)})
    db.commit()
    return {"config": _cfg_dict(c), "vault_enabled": vault.available(), "credentials_cleared": bool(changed_target)}


@admin_router.delete("/{app_id}/swa")
def delete_config(app_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    a = _swa_app(db, app_id)
    c = db.query(SwaConfig).filter(SwaConfig.application_id == a.id).first()
    if c is None:
        raise HTTPException(status_code=404, detail="No SWA configuration")
    n = db.query(SwaCredential).filter(SwaCredential.application_id == a.id).delete()
    db.delete(c)
    record(db, AuditAction.APPLICATION_SWA_REMOVED, request, actor, a.id, "application", {"name": a.name, "credentials_removed": n})
    db.commit()
    return {"success": True}


@admin_router.get("/{app_id}/swa/credentials")
def list_credentials(app_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Who has stored a credential. Never the secret, and the username only when the user typed it."""
    a = _swa_app(db, app_id)
    rows = (db.query(SwaCredential, User).join(User, User.id == SwaCredential.user_id)
            .filter(SwaCredential.application_id == a.id).order_by(User.email).limit(500).all())
    return {"items": [{"user_id": u.id, "email": u.email, "username": c.username, "updated_at": c.updated_at.isoformat(),
                       "last_used_at": c.last_used_at.isoformat() if c.last_used_at else None} for c, u in rows]}


@admin_router.delete("/{app_id}/swa/credentials/{user_id}")
def reset_credential(app_id: int, user_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    a = _swa_app(db, app_id)
    n = db.query(SwaCredential).filter(SwaCredential.application_id == a.id, SwaCredential.user_id == user_id).delete()
    if not n:
        raise HTTPException(status_code=404, detail="No stored credential for that user")
    record(db, AuditAction.SWA_CREDENTIAL_RESET, request, actor, user_id, "user", {"application_id": a.id, "name": a.name})
    db.commit()
    return {"success": True}


# ---- the signed-in user ----------------------------------------------------------------------------------------------

def _usable(db: Session, app_id: int, user: User):
    """(application, config) when the user may use this SWA application now; otherwise the same 404 whatever the reason."""
    a = db.get(Application, app_id)
    c = db.query(SwaConfig).filter(SwaConfig.application_id == app_id).first() if a is not None else None
    if a is None or c is None or a.sign_on_mode != "swa" or a.status != "active" or not ent.is_entitled(db, a.id, user.id):
        raise HTTPException(status_code=404, detail="Application not found")
    return a, c


def _credential(db: Session, app_id: int, user_id: int) -> Optional[SwaCredential]:
    return db.query(SwaCredential).filter(SwaCredential.application_id == app_id, SwaCredential.user_id == user_id).first()


def _throttle(scope: str, user: User) -> None:
    ratelimit.check(scope, f"u{user.id}", settings.RATE_LIMIT_AUTHORIZE_REQUESTS)
    ratelimit.hit(scope, f"u{user.id}", settings.RATE_LIMIT_AUTHORIZE_WINDOW_SECONDS)


def _username(c: SwaConfig, cred: SwaCredential, user: User) -> str:
    return {"email": user.email, "username": user.username}.get(c.username_source) or cred.username or ""


@api_router.get("/apps/{app_id}")
def status(app_id: int, response: Response, ctx=Depends(get_session_and_user), db: Session = Depends(get_db)):
    _, user, _ = ctx
    a, c = _usable(db, app_id, user)
    cred = _credential(db, a.id, user.id)
    response.headers.update(NO_STORE)
    return {"name": a.name, "username_source": c.username_source, "has_credential": cred is not None,
            "username": _username(c, cred, user) if cred else None, "login_host": urlsplit(c.login_url).netloc, "vault_enabled": vault.available()}


class CredentialBody(BaseModel):
    username: Optional[str] = Field(None, max_length=255)
    password: str = Field(..., min_length=1, max_length=256)


@api_router.put("/apps/{app_id}/credential")
def set_credential(app_id: int, body: CredentialBody, request: Request, ctx=Depends(get_session_and_user), db: Session = Depends(get_db)):
    _, user, _ = ctx
    a, c = _usable(db, app_id, user)
    _throttle("swa_set", user)
    username = (body.username or "").strip() or None
    if c.username_source == "user" and username is None:
        raise HTTPException(status_code=422, detail="Enter your username for this application")
    if "\x00" in body.password or (username and "\x00" in username):
        raise HTTPException(status_code=422, detail="Invalid characters")
    if user.verify_password(body.password):
        # Handing the IdP password to every application would make this vault a single point of failure for all of them.
        raise HTTPException(status_code=422, detail="Use this application's own password, not your IdentityForge password")
    try:
        blob, key_id = vault.encrypt(body.password, user.tenant_id, a.id, user.id)
    except vault.VaultUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    cred = _credential(db, a.id, user.id)
    if cred is None:
        cred = SwaCredential(application_id=a.id, user_id=user.id)
        db.add(cred)
    cred.username = username if c.username_source == "user" else None
    cred.secret, cred.key_id, cred.updated_at = blob, key_id, _now()
    record(db, AuditAction.SWA_CREDENTIAL_SET, request, user, a.id, "application", {"name": a.name})
    db.commit()
    return {"success": True}


@api_router.delete("/apps/{app_id}/credential")
def remove_credential(app_id: int, request: Request, ctx=Depends(get_session_and_user), db: Session = Depends(get_db)):
    _, user, _ = ctx
    a = db.get(Application, app_id)
    if a is None or db.query(SwaCredential).filter(SwaCredential.application_id == app_id, SwaCredential.user_id == user.id).delete() == 0:
        raise HTTPException(status_code=404, detail="No stored credential")
    record(db, AuditAction.SWA_CREDENTIAL_REMOVED, request, user, a.id, "application", {"name": a.name})
    db.commit()
    return {"success": True}


@api_router.post("/apps/{app_id}/launch")
def launch(app_id: int, request: Request, response: Response, ctx=Depends(get_session_and_user), db: Session = Depends(get_db)):
    session, user, _ = ctx
    a, c = _usable(db, app_id, user)
    _throttle("swa_launch", user)
    if (_now() - session.auth_time).total_seconds() > settings.SWA_FRESH_AUTH_SECONDS:
        # The password is about to reach the browser: a stolen, older session must not be enough to obtain it.
        raise HTTPException(status_code=403, detail="reauthentication_required")
    from backend.app.policies import engine as policy

    pd = policy.check(db, request, a.id, user, session)
    if pd.kind != policy.ALLOW:
        db.commit()  # keeps the policy-denied audit row
        raise HTTPException(status_code=403, detail="reauthentication_required" if pd.kind == policy.REAUTH else pd.reason)
    cred = _credential(db, a.id, user.id)
    if cred is None:
        raise HTTPException(status_code=409, detail="credential_required")
    try:
        password = vault.decrypt(cred.secret, cred.key_id, user.tenant_id, a.id, user.id)
    except (vault.VaultError, vault.VaultUnavailable):
        record(db, AuditAction.SWA_LAUNCH, request, user, a.id, "application", {"name": a.name, "result": "unreadable"})
        db.commit()
        raise HTTPException(status_code=409, detail="credential_required")
    try:
        if vault.available() and cred.key_id != vault.current_key_id():
            cred.secret, cred.key_id = vault.encrypt(password, user.tenant_id, a.id, user.id)
    except vault.VaultUnavailable:
        pass
    cred.last_used_at = _now()
    record(db, AuditAction.SWA_LAUNCH, request, user, a.id, "application", {"name": a.name, "result": "released"})
    db.commit()
    response.headers.update(NO_STORE)
    fields = [{"name": f["name"], "value": f["value"]} for f in (c.extra_fields or [])]
    fields += [{"name": c.username_field, "value": _username(c, cred, user)}, {"name": c.password_field, "value": password}]
    return {"login_url": c.login_url, "fields": fields}
