"""Admin API for OIDC clients ("Applications")."""

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.auth.deps import require_admin
from backend.app.db import get_db
from backend.app.oidc import clients as svc
from backend.app.oidc.models import OIDCClient, OIDCClientSecret
from backend.app.users.model import User

router = APIRouter(prefix="/admin/oidc/clients", tags=["oidc-clients"])


class ClientCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    client_type: str = "public"
    redirect_uris: List[str] = Field(default_factory=list)
    post_logout_redirect_uris: List[str] = Field(default_factory=list)
    allowed_scopes: List[str] = Field(default_factory=lambda: ["openid", "profile", "email"])
    allowed_audiences: List[str] = Field(default_factory=list)  # service clients only
    token_endpoint_auth_method: Optional[str] = None  # confidential/service: client_secret_basic (default) | private_key_jwt
    jwks: Optional[dict] = None  # public keys, required for private_key_jwt
    first_party: bool = False
    initiate_login_uri: Optional[str] = Field(None, max_length=2000)  # https (or loopback) URL that starts sign-in at the app
    launch_url: Optional[str] = Field(None, max_length=2000)  # the application's home page (tile target / target_link_uri)
    require_assignment: bool = False  # only assigned users may sign in; off here so the plain client API keeps its old behaviour
    application_id: Optional[int] = None  # attach to an existing OIDC application without a client (default: create one)
    access_token_format: str = Field("jwt", pattern="^(jwt|opaque)$")  # opaque: revocable via /oauth/revoke, checked by introspection


class ClientUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    redirect_uris: Optional[List[str]] = None
    post_logout_redirect_uris: Optional[List[str]] = None
    allowed_scopes: Optional[List[str]] = None
    allowed_audiences: Optional[List[str]] = None
    jwks: Optional[dict] = None  # replaces the registered keys (private_key_jwt clients)
    status: Optional[str] = Field(None, pattern="^(active|disabled)$")
    first_party: Optional[bool] = None
    access_token_format: Optional[str] = Field(None, pattern="^(jwt|opaque)$")
    initiate_login_uri: Optional[str] = Field(None, max_length=2000)  # empty string clears it


class SecretCreate(BaseModel):
    expires_in_days: Optional[int] = Field(None, ge=1, le=3650)


def _get(db: Session, pk: int) -> OIDCClient:
    c = db.get(OIDCClient, pk)
    if c is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return c


def _detail(db: Session, c: OIDCClient) -> dict:
    rows = db.query(OIDCClientSecret).filter(OIDCClientSecret.client_pk == c.id).order_by(OIDCClientSecret.id).all()
    return svc.client_to_dict(c, rows)


def _only_super_admin_sets_first_party(actor: User) -> None:
    # A first-party client skips the consent screen, so who may grant that is restricted.
    if not actor.is_super_admin:
        raise HTTPException(status_code=403, detail="Only a super administrator can mark a client as first-party")


def _bad(e: svc.ClientError):
    raise HTTPException(status_code=422, detail=str(e))


@router.get("")
def list_clients(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    rows = db.query(OIDCClient).order_by(OIDCClient.id).all()
    return {"items": [_detail(db, c) for c in rows], "supported_scopes": list(svc.SUPPORTED_SCOPES)}


@router.post("", status_code=201)
def create_client(body: ClientCreate, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    if body.client_type not in svc.CLIENT_TYPES:
        raise HTTPException(status_code=422, detail="client_type must be public, confidential or service")
    service = body.client_type == "service"
    if body.client_type == "public":
        if body.token_endpoint_auth_method not in (None, "none") or body.jwks is not None:
            raise HTTPException(status_code=422, detail="a public client has no client authentication")
        method = "none"
    else:
        method = body.token_endpoint_auth_method or "client_secret_basic"
        if method not in svc.AUTH_METHODS:
            raise HTTPException(status_code=422, detail="token_endpoint_auth_method must be client_secret_basic or private_key_jwt")
        if (method == "private_key_jwt") != (body.jwks is not None):
            raise HTTPException(status_code=422, detail="jwks is required for private_key_jwt and not allowed otherwise")
    if body.first_party:
        _only_super_admin_sets_first_party(actor)
        if service:
            raise HTTPException(status_code=422, detail="a service client has no users, so first-party does not apply")
    if service and not actor.is_super_admin:
        raise HTTPException(status_code=403, detail="Only a super administrator can create a service client")  # it acts without any user
    try:
        if service:
            if body.redirect_uris or body.post_logout_redirect_uris:
                raise svc.ClientError("a service client has no redirect URIs")
            redirects, logouts = [], []
            scopes = svc.validate_service_scopes(body.allowed_scopes)
            audiences = svc.validate_audiences(body.allowed_audiences)
        else:
            if body.allowed_audiences:
                raise svc.ClientError("audiences apply to service clients only")
            redirects = svc.validate_uri_list(body.redirect_uris, "redirect URI", required=True)
            logouts = svc.validate_uri_list(body.post_logout_redirect_uris, "post-logout redirect URI", required=False)
            scopes = svc.validate_scopes(body.allowed_scopes)
            audiences = []
        jwks = svc.validate_jwks(body.jwks) if body.jwks is not None else None
        initiate = svc.validate_redirect_uri(body.initiate_login_uri, "initiate login URI") if body.initiate_login_uri else None
        if initiate and service:
            raise svc.ClientError("a service client has no users to sign in")
    except svc.ClientError as e:
        _bad(e)
    client = OIDCClient(
        initiate_login_uri=initiate,
        client_id=svc.new_client_id(),
        name=body.name.strip(),
        description=body.description,
        client_type=body.client_type,
        token_endpoint_auth_method=method,
        jwks=jwks,
        first_party=body.first_party,
        access_token_format=body.access_token_format,
        status="active",
        redirect_uris=redirects,
        post_logout_redirect_uris=logouts,
        allowed_scopes=scopes,
        allowed_audiences=audiences,
        grant_types=["client_credentials"] if service else svc.grant_types_for(scopes),
        created_by=actor.id,
    )
    db.add(client)
    db.flush()
    from backend.app.applications.entitlement import ensure_for_client
    from backend.app.applications.routes import _launch_url

    if body.application_id is None:
        ensure_for_client(db, client, actor.id, launch_url=_launch_url(body.launch_url), require_assignment=body.require_assignment)
    else:
        from backend.app.applications.models import Application

        target = db.get(Application, body.application_id)
        if target is None or target.sign_on_mode != "oidc" or db.query(OIDCClient.id).filter(OIDCClient.application_id == target.id).first():
            raise HTTPException(status_code=422, detail="application_id must be an OIDC application without a client")
        client.application_id = target.id
    raw = svc.add_secret(db, client) if method == "client_secret_basic" else None
    record(db, AuditAction.OIDC_CLIENT_CREATED, request, actor, client.id, "oidc_client",
           {"client_id": client.client_id, "name": client.name, "type": client.client_type, "first_party": client.first_party})
    db.commit()
    out = _detail(db, client)
    if raw:
        out["client_secret"] = raw  # shown once
    return out


@router.get("/{pk}")
def get_client(pk: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return _detail(db, _get(db, pk))


@router.patch("/{pk}")
def update_client(pk: int, body: ClientUpdate, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    c = _get(db, pk)
    changed = {}
    try:
        if body.name is not None:
            c.name = body.name.strip(); changed["name"] = True
        if body.description is not None:
            c.description = body.description; changed["description"] = True
        service = c.client_type == "service"
        if service and (body.redirect_uris or body.post_logout_redirect_uris):
            raise svc.ClientError("a service client has no redirect URIs")
        if body.jwks is not None:
            if c.token_endpoint_auth_method != "private_key_jwt":
                raise svc.ClientError("jwks applies to private_key_jwt clients only")
            c.jwks = svc.validate_jwks(body.jwks); changed["jwks"] = True
        if body.allowed_audiences is not None:
            if not service:
                raise svc.ClientError("audiences apply to service clients only")
            c.allowed_audiences = svc.validate_audiences(body.allowed_audiences); changed["allowed_audiences"] = True
        if body.redirect_uris is not None and not service:
            c.redirect_uris = svc.validate_uri_list(body.redirect_uris, "redirect URI", required=True); changed["redirect_uris"] = True
        if body.post_logout_redirect_uris is not None and not service:
            c.post_logout_redirect_uris = svc.validate_uri_list(body.post_logout_redirect_uris, "post-logout redirect URI", required=False)
            changed["post_logout_redirect_uris"] = True
        if body.allowed_scopes is not None:
            if service:
                c.allowed_scopes = svc.validate_service_scopes(body.allowed_scopes)
            else:
                c.allowed_scopes = svc.validate_scopes(body.allowed_scopes)
                c.grant_types = svc.grant_types_for(c.allowed_scopes)
            changed["allowed_scopes"] = True
    except svc.ClientError as e:
        _bad(e)
    if body.initiate_login_uri is not None:
        try:
            new = svc.validate_redirect_uri(body.initiate_login_uri, "initiate login URI") if body.initiate_login_uri else None
        except svc.ClientError as e:
            _bad(e)
        if new and c.client_type == "service":
            raise HTTPException(status_code=422, detail="a service client has no users to sign in")
        c.initiate_login_uri = new; changed["initiate_login_uri"] = True
    if body.first_party is not None and body.first_party != c.first_party:
        _only_super_admin_sets_first_party(actor)
        c.first_party = body.first_party; changed["first_party"] = body.first_party
    if body.access_token_format is not None and body.access_token_format != c.access_token_format:
        c.access_token_format = body.access_token_format; changed["access_token_format"] = body.access_token_format
    if body.status is not None and body.status != c.status:
        c.status = body.status; changed["status"] = body.status
    if changed:
        c.updated_at = datetime.now(timezone.utc)
        record(db, AuditAction.OIDC_CLIENT_UPDATED, request, actor, c.id, "oidc_client", {"changed": changed})
    db.commit()
    return _detail(db, c)


@router.delete("/{pk}")
def delete_client(pk: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    c = _get(db, pk)
    name, cid = c.name, c.client_id
    from backend.app.applications.entitlement import drop_for_client

    drop_for_client(db, c)
    db.flush()
    db.delete(c)
    record(db, AuditAction.OIDC_CLIENT_DELETED, request, actor, pk, "oidc_client", {"client_id": cid, "name": name})
    db.commit()
    return {"success": True}


@router.post("/{pk}/secrets", status_code=201)
def add_client_secret(pk: int, body: SecretCreate, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    c = _get(db, pk)
    try:
        raw = svc.add_secret(db, c, body.expires_in_days)
    except svc.ClientError as e:
        raise HTTPException(status_code=409, detail=str(e))
    record(db, AuditAction.OIDC_CLIENT_SECRET_ROTATED, request, actor, c.id, "oidc_client", {"client_id": c.client_id})
    db.commit()
    return {**_detail(db, c), "client_secret": raw}


@router.delete("/{pk}/secrets/{secret_id}")
def revoke_client_secret(pk: int, secret_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    c = _get(db, pk)
    s = db.query(OIDCClientSecret).filter(OIDCClientSecret.id == secret_id, OIDCClientSecret.client_pk == c.id).first()
    if s is None:
        raise HTTPException(status_code=404, detail="Secret not found")
    if s.revoked_at is None:
        s.revoked_at = datetime.now(timezone.utc)
        record(db, AuditAction.OIDC_CLIENT_SECRET_REVOKED, request, actor, c.id, "oidc_client", {"client_id": c.client_id})
    db.commit()
    return _detail(db, c)
