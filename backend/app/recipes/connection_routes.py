"""Connection workspaces, generic HTTP auth and browser-bound OAuth authorization."""
import base64
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlsplit
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from backend.app.auth.deps import require_admin
from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.config import settings
from backend.app.db import get_db
from backend.app.recipes import access, crypto, http_auth
from backend.app.recipes.models import RecipeConnection, RecipeFolder, ConnectionOAuthState
from backend.app.recipes.sharing import SharingBody, apply_sharing, checked_groups
from backend.app.users.model import User

router = APIRouter(tags=["connections"])
NOW = lambda: datetime.now(timezone.utc)


def enabled():
    if not settings.RECIPES_ENABLED:
        raise HTTPException(404, "Recipes are not enabled")


router.dependencies.append(Depends(enabled))


class FolderBody(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    use_group_ids: list[int] = Field(default_factory=list, max_length=100)
    manage_group_ids: list[int] = Field(default_factory=list, max_length=100)


def folder_view(f, actor):
    return {"id": f.id, "name": f.name, "use_group_ids": f.use_group_ids, "manage_group_ids": f.manage_group_ids,
            "can_manage": access.can_manage_folder(actor, f)}


@router.get("/admin/recipe-folders")
def folders(db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    return {"items": [folder_view(f, actor) for f in db.query(RecipeFolder).order_by(RecipeFolder.name)
                      if access.can_use_folder(actor, f) or access.can_manage_folder(actor, f)]}


def save_folder(db, actor, body, f):
    if not body.name.strip():
        raise HTTPException(422, "Give the folder a name")
    f.name = body.name.strip()
    f.use_group_ids = checked_groups(db, body.use_group_ids)
    f.manage_group_ids = checked_groups(db, body.manage_group_ids)
    db.add(f)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Folder name is already in use")
    return f


@router.post("/admin/recipe-folders", status_code=201)
def create_folder(body: FolderBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    f = save_folder(db, actor, body, RecipeFolder(created_by=actor.id))
    record(db, AuditAction.RECIPE_SETTINGS_CHANGED, request, actor, f.id, "recipe_folder", {"operation": "created", "name": f.name})
    db.commit()
    return folder_view(f, actor)


@router.put("/admin/recipe-folders/{fid}")
def update_folder(fid: int, body: FolderBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    f = db.get(RecipeFolder, fid)
    if f is None or not access.can_manage_folder(actor, f):
        raise HTTPException(403, "You do not manage this folder")
    save_folder(db, actor, body, f)
    record(db, AuditAction.RECIPE_SETTINGS_CHANGED, request, actor, f.id, "recipe_folder", {"operation": "updated", "name": f.name})
    db.commit()
    return folder_view(f, actor)


class HttpConnectionBody(SharingBody):
    name: str = Field(min_length=1, max_length=100)
    allowed_host: str = Field(min_length=1, max_length=255)
    allowed_paths: list[str] = Field(default_factory=list, max_length=20)
    config: dict = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict, max_length=20)


def need_connection(db, actor, cid, *, manage=False):
    c = db.get(RecipeConnection, cid)
    if c is None:
        raise HTTPException(404, "Connection not found")
    if not (access.can_manage_connection if manage else access.can_use_connection)(actor, c):
        raise HTTPException(403, "You do not have permission to use or manage this connection")
    return c


def save_http(db, actor, body, c, *, creating=False):
    from backend.app.recipes.routes import ConnectionBody, _conn_checks, _need_key
    _need_key()
    if not body.name.strip():
        raise HTTPException(422, "Give the connection a name")
    host = _conn_checks(ConnectionBody(name=body.name, kind="bearer", allowed_host=body.allowed_host, allowed_paths=body.allowed_paths))
    try:
        cfg = http_auth.config(body.config)
        unchanged = not creating and c.config == cfg.model_dump() and c.allowed_host == host and (c.allowed_paths or []) == body.allowed_paths
        old = http_auth.values(c) if unchanged else {}
        sec = http_auth.validate_secrets(cfg, body.secrets, old)
    except http_auth.AuthError as e:
        raise HTTPException(422, str(e)) from None
    if not unchanged or body.secrets:
        # Changing settings or rotating credentials invalidates OAuth tokens and old scope assertions.
        sec = {k: v for k, v in sec.items() if k in http_auth.required_keys(cfg)}
        c.granted_scopes, c.scopes_checked_at = None, None
    c.name, c.kind, c.allowed_host, c.allowed_paths = body.name.strip(), "http", host, body.allowed_paths
    c.config, c.secret_enc, c.updated_at = cfg.model_dump(), crypto.encrypt(json.dumps(sec)), NOW()
    apply_sharing(db, actor, c, body, creating=creating)
    db.add(c)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Connection name is already in use")
    return c


def http_saved(db, actor, request, c, created):
    from backend.app.recipes.routes import _conn_dict
    record(db, AuditAction.RECIPE_CONNECTION_CREATED if created else AuditAction.RECIPE_CONNECTION_UPDATED,
           request, actor, c.id, "recipe_connection", {"name": c.name, "host": c.allowed_host, "kind": "http"})
    db.commit()
    return _conn_dict(c, actor)


@router.post("/admin/recipe-connections/http", status_code=201)
def create_http(body: HttpConnectionBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    c = save_http(db, actor, body, RecipeConnection(created_by=actor.id), creating=True)
    return http_saved(db, actor, request, c, True)


@router.put("/admin/recipe-connections/http/{cid}")
def update_http(cid: int, body: HttpConnectionBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    c = need_connection(db, actor, cid, manage=True)
    if c.kind in ("connector", "slack_webhook"):
        raise HTTPException(409, "This is not a generic HTTP connection")
    save_http(db, actor, body, c)
    return http_saved(db, actor, request, c, False)


def callback_url():
    u = urlsplit(settings.RECIPE_OAUTH_CALLBACK_URL)
    if u.scheme != "https" or not u.hostname or u.username or u.password or u.query or u.fragment or u.path != "/api/v1/admin/recipe-connections/oauth/callback":
        raise HTTPException(409, "Configure RECIPE_OAUTH_CALLBACK_URL with the exact public HTTPS callback")
    return settings.RECIPE_OAUTH_CALLBACK_URL


@router.post("/admin/recipe-connections/{cid}/oauth/start")
def oauth_start(cid: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    c = need_connection(db, actor, cid, manage=True)
    cfg = http_auth.config(c.config) if c.kind == "http" else None
    if cfg is None or cfg.auth_type != "oauth2_authorization_code":
        raise HTTPException(409, "Choose OAuth authorization code authentication")
    redirect_uri = callback_url()
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    from sqlalchemy import or_, and_
    db.query(ConnectionOAuthState).filter(or_(ConnectionOAuthState.expires_at < NOW(),
        and_(ConnectionOAuthState.actor_id == actor.id, ConnectionOAuthState.connection_id == c.id))).delete(synchronize_session=False)
    db.add(ConnectionOAuthState(id=hashlib.sha256(state.encode()).hexdigest(), connection_id=c.id, actor_id=actor.id,
                               verifier_enc=crypto.encrypt(verifier), connection_updated_at=c.updated_at,
                               expires_at=NOW() + timedelta(minutes=10)))
    db.commit()
    return {"authorization_url": cfg.authorization_url + "?" + urlencode({
        "response_type": "code", "client_id": cfg.client_id, "redirect_uri": redirect_uri, "scope": cfg.scope,
        "state": state, "code_challenge": challenge, "code_challenge_method": "S256"})}


@router.get("/admin/recipe-connections/oauth/callback")
def oauth_callback(request: Request, state: str = "", code: str = "", error: str = "",
                   db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    if not 20 <= len(state) <= 200 or len(code) > 4000:
        raise HTTPException(400, "Invalid or expired authorization")
    row = db.query(ConnectionOAuthState).filter(ConnectionOAuthState.id == hashlib.sha256(state.encode()).hexdigest()).with_for_update().first()
    if row is None or row.actor_id != actor.id or row.expires_at < NOW():
        raise HTTPException(400, "Invalid or expired authorization")
    c = need_connection(db, actor, row.connection_id, manage=True)
    if c.updated_at != row.connection_updated_at:
        raise HTTPException(409, "Connection settings changed; authorize again")
    verifier = crypto.decrypt(row.verifier_enc)
    db.delete(row)
    db.commit()  # One use even if the provider refuses the exchange.
    if error or not code:
        raise HTTPException(400, "Authorization was not completed")
    try:
        cfg = http_auth.config(c.config)
        sec, scopes = http_auth.token_request(cfg, http_auth.values(c), {
            "grant_type": "authorization_code", "code": code, "code_verifier": verifier, "redirect_uri": callback_url()})
    except http_auth.AuthError:
        raise HTTPException(400, "Authorization failed; check the connection settings") from None
    # Recheck after network I/O; never overwrite credentials rotated by another administrator.
    c = db.query(RecipeConnection).filter(RecipeConnection.id == c.id).populate_existing().with_for_update().one()
    if c.updated_at != row.connection_updated_at or not access.can_manage_connection(actor, c):
        raise HTTPException(409, "Connection changed; authorize again")
    c.secret_enc, c.granted_scopes, c.scopes_checked_at, c.updated_at = crypto.encrypt(json.dumps(sec)), scopes, NOW(), NOW()
    record(db, AuditAction.RECIPE_CONNECTION_UPDATED, request, actor, c.id, "recipe_connection", {"operation": "authorized"})
    db.commit()
    return HTMLResponse("<!doctype html><title>Ifora connection authorized</title><h1>Connection authorized</h1>"
                        "<p>You can close this tab and return to your recipe.</p>",
                        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                                 "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'"})


@router.post("/admin/recipe-connections/{cid}/check")
def check_http(cid: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    c = need_connection(db, actor, cid)
    if c.kind != "http":
        raise HTTPException(409, "Use the connector's test action")
    try:
        cfg = http_auth.config(c.config)
        sec = http_auth.values(c)
        if cfg.auth_type.startswith("oauth2"):
            from backend.app.recipes.actions import http_overrides
            http_auth.access_token(db, c, cfg, **{k: v for k, v in http_overrides.items() if k in ("policy", "resolver", "transport")})
            message = "OAuth token is available. Test a recipe action to verify resource permissions."
        else:
            http_auth.validate_secrets(cfg, {}, sec)
            message = "Credential fields are configured. Test a recipe action to verify remote authentication."
        ok = True
    except http_auth.AuthError:
        ok, message = False, "Check the credentials or authorize this connection."
    record(db, AuditAction.RECIPE_CONNECTION_TESTED, request, actor, c.id, "recipe_connection", {"ok": ok})
    db.commit()
    return {"ok": ok, "message": message}
