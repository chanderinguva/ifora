"""Applications API (ADR 010): admin management, shared assignments, and the end user's "My apps"."""

import base64
import binascii
import hashlib
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.applications import entitlement as ent
from backend.app.applications.models import Application, ApplicationAssignment, ApplicationIcon, SIGN_ON_MODES
from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.auth.deps import get_current_user, require_admin
from backend.app.config import settings
from backend.app.db import get_db
from backend.app.groups import standards
from backend.app.groups.model import Group
from backend.app.oidc.models import OIDCClient
from backend.app.provisioning.models import ProvisioningApp
from backend.app.saml.models import SamlProvider
from backend.app.swa.models import SwaConfig
from backend.app.users.model import User

router = APIRouter(prefix="/admin/applications", tags=["applications"])
me_router = APIRouter(prefix="/me/apps", tags=["applications"])
MAX_APPLICATIONS = 500


def _launch_url(v: Optional[str]) -> Optional[str]:
    if v is None or not v.strip():
        return None
    v = v.strip()
    parts = urlsplit(v)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise HTTPException(status_code=422, detail="launch_url must be an http(s) URL without credentials")
    return v


class AppBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    sign_on_mode: str = Field("none", pattern="^(" + "|".join(SIGN_ON_MODES) + ")$")
    launch_url: Optional[str] = Field(None, max_length=2000)
    status: str = Field("active", pattern="^(active|inactive)$")
    visible: bool = True
    require_assignment: bool = True
    # Governance metadata. Omitted on update = left as it is (older clients send only the fields above).
    owner_user_id: Optional[int] = None
    sensitivity: Optional[str] = None
    review_by: Optional[date] = None
    tags: List[str] = Field(default_factory=list)
    attributes: Dict[str, Any] = Field(default_factory=dict)


def _apply_meta(db: Session, a: Application, body: AppBody, only_sent: bool) -> None:
    sent = body.model_fields_set
    if body.sensitivity is not None and body.sensitivity not in standards.SENSITIVITY:
        raise HTTPException(status_code=422, detail="sensitivity must be low, medium or high")
    if body.owner_user_id is not None and db.get(User, body.owner_user_id) is None:
        raise HTTPException(status_code=422, detail="Owner not found")
    if not only_sent or "owner_user_id" in sent:
        a.owner_user_id = body.owner_user_id
    if not only_sent or "sensitivity" in sent:
        a.sensitivity = body.sensitivity
    if not only_sent or "review_by" in sent:
        a.review_by = body.review_by
    if not only_sent or "tags" in sent:
        a.tags = standards.clean_tags(body.tags)
    if not only_sent or "attributes" in sent:
        a.attributes = standards.clean_attributes(body.attributes)


def _checked(body: AppBody) -> Optional[str]:
    url = _launch_url(body.launch_url)
    if body.sign_on_mode == "bookmark" and url is None:
        raise HTTPException(status_code=422, detail="A bookmark application needs a launch URL")
    if body.sign_on_mode == "none":
        url = None
    return url


def _dict(db: Session, a: Application) -> dict:
    client = db.query(OIDCClient).filter(OIDCClient.application_id == a.id).first()
    saml = db.query(SamlProvider).filter(SamlProvider.application_id == a.id).first()
    swa = db.query(SwaConfig).filter(SwaConfig.application_id == a.id).first()
    prov = db.query(ProvisioningApp).filter(ProvisioningApp.application_id == a.id).first()
    n = lambda q: q.scalar() or 0  # noqa: E731
    return {
        "id": a.id, "public_id": a.public_id, "name": a.name, "description": a.description, "sign_on_mode": a.sign_on_mode,
        "launch_url": a.launch_url, "status": a.status, "visible": a.visible, "require_assignment": a.require_assignment,
        "oidc_client": {"id": client.id, "client_id": client.client_id, "name": client.name, "client_type": client.client_type} if client else None,
        "saml": {"sp_entity_id": saml.sp_entity_id, "acs_url": saml.acs_url} if saml else None,
        "swa": {"login_url": swa.login_url} if swa else None,
        "provisioning": {"id": prov.id, "kind": prov.kind, "enabled": prov.enabled} if prov else None,
        "owner_user_id": a.owner_user_id, "sensitivity": a.sensitivity, "review_by": a.review_by.isoformat() if a.review_by else None,
        "tags": list(a.tags or []), "attributes": dict(a.attributes or {}),
        "has_icon": db.get(ApplicationIcon, a.id) is not None,
        "assigned_users": n(db.query(func.count(ApplicationAssignment.id)).filter(ApplicationAssignment.application_id == a.id, ApplicationAssignment.user_id.is_not(None))),
        "assigned_groups": n(db.query(func.count(ApplicationAssignment.id)).filter(ApplicationAssignment.application_id == a.id, ApplicationAssignment.group_id.is_not(None))),
        "created_at": a.created_at.isoformat(), "updated_at": a.updated_at.isoformat(),
    }


def _get(db: Session, app_id: int) -> Application:
    a = db.get(Application, app_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return a


@router.get("")
def list_applications(q: str = Query("", max_length=100), owner_user_id: Optional[int] = Query(None), sensitivity: str = Query("", max_length=8),
                      tag: str = Query("", max_length=30), db: Session = Depends(get_db), _: User = Depends(require_admin)):
    query = db.query(Application)
    if q.strip():
        like = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.filter(Application.name.ilike(like, escape="\\"))
    if owner_user_id is not None:
        query = query.filter(Application.owner_user_id == owner_user_id)
    if sensitivity:
        query = query.filter(Application.sensitivity == sensitivity)
    if tag:
        query = query.filter(Application.tags.contains([tag.lower()]))
    return {"items": [_dict(db, a) for a in query.order_by(Application.name).limit(MAX_APPLICATIONS).all()]}


@router.post("", status_code=201)
def create_application(body: AppBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    url = _checked(body)
    if db.query(func.count(Application.id)).scalar() >= MAX_APPLICATIONS:
        raise HTTPException(status_code=409, detail=f"At most {MAX_APPLICATIONS} applications")
    a = Application(public_id=str(uuid.uuid4()), name=body.name.strip(), description=body.description, sign_on_mode=body.sign_on_mode,
                    launch_url=url, status=body.status, visible=body.visible, require_assignment=body.require_assignment, created_by=actor.id)
    _apply_meta(db, a, body, only_sent=False)
    db.add(a)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Application name already in use")
    record(db, AuditAction.APPLICATION_CREATED, request, actor, a.id, "application", {"name": a.name, "sign_on_mode": a.sign_on_mode})
    db.commit()
    return _dict(db, a)


# ---- OIDC templates ---------------------------------------------------------------------------------------------

TEMPLATES = {
    "web": {"label": "Web application", "client_type": "confidential", "needs_redirects": True, "has_secret": True,
            "description": "Server-side app (Rails, Django, Spring, ASP.NET…). Authorization code flow with a client secret kept on the server."},
    "spa": {"label": "Single-page application", "client_type": "public", "needs_redirects": True, "has_secret": False,
            "description": "Browser app with no back end (React, Vue, Angular…). Authorization code flow with PKCE; no secret exists."},
    "native": {"label": "Native / desktop app", "client_type": "public", "needs_redirects": True, "has_secret": False,
               "description": "Mobile or desktop app. Authorization code flow with PKCE; use an https app-link or a loopback http://127.0.0.1 redirect (custom URL schemes are not supported yet)."},
    "service": {"label": "Service (machine to machine)", "client_type": "service", "needs_redirects": False, "has_secret": True,
                "description": "Back-end service with no user. Client credentials flow; super administrators only."},
}


class FromTemplate(BaseModel):
    template: str
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    redirect_uris: List[str] = Field(default_factory=list)
    post_logout_redirect_uris: List[str] = Field(default_factory=list)
    launch_url: Optional[str] = Field(None, max_length=2000)
    initiate_login_uri: Optional[str] = Field(None, max_length=2000)
    require_assignment: bool = True  # secure default for the unified flow (the plain client API keeps off)
    allowed_scopes: Optional[List[str]] = None
    allowed_audiences: List[str] = Field(default_factory=list)


@router.get("/templates")
def templates(_: User = Depends(require_admin)):
    return {"items": [{"id": k, **v} for k, v in TEMPLATES.items()]}


@router.post("/from-template", status_code=201)
def from_template(body: FromTemplate, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    """An application and its OIDC client in one transaction; the client secret (if any) is returned once."""
    from backend.app.oidc import client_routes as cr

    t = TEMPLATES.get(body.template)
    if t is None:
        raise HTTPException(status_code=422, detail="Unknown template")
    if db.query(Application.id).filter(Application.name == body.name.strip()).first():
        raise HTTPException(status_code=409, detail="Application name already in use")
    service = t["client_type"] == "service"
    scopes = body.allowed_scopes or (["api:read"] if service else ["openid", "profile", "email"])
    return cr.create_client(
        cr.ClientCreate(name=body.name, description=body.description, client_type=t["client_type"], redirect_uris=body.redirect_uris,
                        post_logout_redirect_uris=body.post_logout_redirect_uris, allowed_scopes=scopes, allowed_audiences=body.allowed_audiences,
                        launch_url=body.launch_url, initiate_login_uri=body.initiate_login_uri, require_assignment=body.require_assignment),
        request, db, actor)


@router.get("/{app_id}")
def get_application(app_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return _dict(db, _get(db, app_id))


@router.put("/{app_id}")
def update_application(app_id: int, body: AppBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    a = _get(db, app_id)
    url = _checked(body)
    if body.sign_on_mode == "oidc" and not db.query(OIDCClient.id).filter(OIDCClient.application_id == a.id).first() and a.sign_on_mode != "oidc":
        pass  # allowed: the client is attached next
    if body.sign_on_mode != "saml" and db.query(SamlProvider.id).filter(SamlProvider.application_id == a.id).first():
        raise HTTPException(status_code=409, detail="Remove the SAML configuration before changing the sign-on mode")
    if body.sign_on_mode != "oidc" and db.query(OIDCClient.id).filter(OIDCClient.application_id == a.id).first():
        raise HTTPException(status_code=409, detail="Detach the OIDC client before changing the sign-on mode")
    if body.sign_on_mode != "swa" and db.query(SwaConfig.id).filter(SwaConfig.application_id == a.id).first():
        raise HTTPException(status_code=409, detail="Remove the Secure Web Authentication configuration (and the stored credentials) before changing the sign-on mode")
    a.name, a.description, a.sign_on_mode, a.launch_url = body.name.strip(), body.description, body.sign_on_mode, url
    a.status, a.visible, a.require_assignment, a.updated_at = body.status, body.visible, body.require_assignment, datetime.now(timezone.utc)
    _apply_meta(db, a, body, only_sent=True)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Application name already in use")
    record(db, AuditAction.APPLICATION_UPDATED, request, actor, a.id, "application",
           {"name": a.name, "sign_on_mode": a.sign_on_mode, "status": a.status, "require_assignment": a.require_assignment})
    db.commit()
    return _dict(db, a)


@router.delete("/{app_id}")
def delete_application(app_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    a = _get(db, app_id)
    if db.query(ProvisioningApp.id).filter(ProvisioningApp.application_id == a.id).first():
        raise HTTPException(status_code=409, detail="Remove its provisioning first (Provisioning apps)")
    name = a.name
    db.delete(a)  # assignments go with it; an attached OIDC client stays, unlinked
    record(db, AuditAction.APPLICATION_DELETED, request, actor, app_id, "application", {"name": name})
    db.commit()
    return {"success": True}


# ---- OIDC facet ---------------------------------------------------------------------------------------------------

class AttachBody(BaseModel):
    client_pk: int


@router.post("/{app_id}/oidc-client")
def attach_oidc_client(app_id: int, body: AttachBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    a = _get(db, app_id)
    if a.sign_on_mode != "oidc":
        raise HTTPException(status_code=409, detail="Set the sign-on mode to OIDC first")
    if db.query(OIDCClient.id).filter(OIDCClient.application_id == a.id).first():
        raise HTTPException(status_code=409, detail="An OIDC client is already attached")
    c = db.get(OIDCClient, body.client_pk)
    if c is None:
        raise HTTPException(status_code=404, detail="OIDC client not found")
    if c.application_id is not None:
        raise HTTPException(status_code=409, detail="That client belongs to another application")
    c.application_id = a.id
    record(db, AuditAction.APPLICATION_OIDC_ATTACHED, request, actor, a.id, "application", {"client_id": c.client_id})
    db.commit()
    return _dict(db, a)


@router.delete("/{app_id}/oidc-client")
def detach_oidc_client(app_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    a = _get(db, app_id)
    c = db.query(OIDCClient).filter(OIDCClient.application_id == a.id).first()
    if c is None:
        raise HTTPException(status_code=404, detail="No OIDC client attached")
    c.application_id = None
    record(db, AuditAction.APPLICATION_OIDC_DETACHED, request, actor, a.id, "application", {"client_id": c.client_id})
    db.commit()
    return _dict(db, a)


# ---- icon -----------------------------------------------------------------------------------------------------

MAX_ICON_BYTES = 100 * 1024


class IconBody(BaseModel):
    data: str = Field(..., max_length=140_000)  # base64 of a PNG, JPEG or WebP


def _sniff(raw: bytes) -> Optional[str]:
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return None


def _icon_response(icon: ApplicationIcon) -> Response:
    return Response(content=icon.data, media_type=icon.content_type, headers={
        "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'",
        "Cache-Control": "private, max-age=300", "ETag": f'"{icon.sha256[:32]}"'})


@router.put("/{app_id}/icon")
def set_icon(app_id: int, body: IconBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    a = _get(db, app_id)
    try:
        raw = base64.b64decode(body.data, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=422, detail="Icon is not valid base64")
    if not raw or len(raw) > MAX_ICON_BYTES:
        raise HTTPException(status_code=422, detail=f"Icon must be at most {MAX_ICON_BYTES // 1024} KB")
    ctype = _sniff(raw)
    if ctype is None:
        raise HTTPException(status_code=422, detail="Icon must be a PNG, JPEG or WebP image")
    icon = db.get(ApplicationIcon, a.id)
    digest = hashlib.sha256(raw).hexdigest()
    if icon is None:
        db.add(ApplicationIcon(application_id=a.id, content_type=ctype, data=raw, sha256=digest, updated_at=datetime.now(timezone.utc)))
    else:
        icon.content_type, icon.data, icon.sha256, icon.updated_at = ctype, raw, digest, datetime.now(timezone.utc)
    record(db, AuditAction.APPLICATION_ICON_SET, request, actor, a.id, "application", {"bytes": len(raw), "type": ctype})
    db.commit()
    return _dict(db, a)


@router.delete("/{app_id}/icon")
def remove_icon(app_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    a = _get(db, app_id)
    icon = db.get(ApplicationIcon, a.id)
    if icon is None:
        raise HTTPException(status_code=404, detail="No icon")
    db.delete(icon)
    record(db, AuditAction.APPLICATION_ICON_REMOVED, request, actor, a.id, "application", {})
    db.commit()
    return _dict(db, a)


@router.get("/{app_id}/icon")
def get_icon(app_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    icon = db.get(ApplicationIcon, _get(db, app_id).id)
    if icon is None:
        raise HTTPException(status_code=404, detail="No icon")
    return _icon_response(icon)


# ---- assignments -------------------------------------------------------------------------------------------------

class AssignBody(BaseModel):
    user_id: Optional[int] = None
    group_id: Optional[int] = None


def _assignment_dict(db: Session, x: ApplicationAssignment) -> dict:
    if x.user_id:
        u = db.get(User, x.user_id)
        return {"id": x.id, "type": "user", "subject_id": x.user_id, "name": f"{u.first_name} {u.last_name}".strip() if u else "", "detail": u.email if u else ""}
    g = db.get(Group, x.group_id)
    return {"id": x.id, "type": "group", "subject_id": x.group_id, "name": g.name if g else "", "detail": "all members"}


@router.get("/{app_id}/assignments")
def list_assignments(app_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    _get(db, app_id)
    rows = db.query(ApplicationAssignment).filter(ApplicationAssignment.application_id == app_id).order_by(ApplicationAssignment.id).limit(500).all()
    return {"items": [_assignment_dict(db, x) for x in rows]}


@router.post("/{app_id}/assignments", status_code=201)
def add_assignment(app_id: int, body: AssignBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    from backend.app.provisioning import service as prov

    a = _get(db, app_id)
    if (body.user_id is None) == (body.group_id is None):
        raise HTTPException(status_code=422, detail="Give either user_id or group_id")
    if body.user_id is not None and db.get(User, body.user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    if body.group_id is not None and db.get(Group, body.group_id) is None:
        raise HTTPException(status_code=404, detail="Group not found")
    x = ApplicationAssignment(application_id=a.id, user_id=body.user_id, group_id=body.group_id, created_by=actor.id)
    db.add(x)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Already assigned")
    affected: List[int] = [body.user_id] if body.user_id is not None else prov.group_members(db, body.group_id)
    prov.on_assignment_change(db, a.id, affected, body.group_id)
    record(db, AuditAction.APPLICATION_ASSIGNMENT_ADDED, request, actor, a.id, "application", {"user_id": body.user_id, "group_id": body.group_id})
    db.commit()
    return _assignment_dict(db, x)


@router.delete("/{app_id}/assignments/{assignment_id}")
def remove_assignment(app_id: int, assignment_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    from backend.app.provisioning import service as prov

    a = _get(db, app_id)
    x = db.get(ApplicationAssignment, assignment_id)
    if x is None or x.application_id != a.id:
        raise HTTPException(status_code=404, detail="Assignment not found")
    uid, gid = x.user_id, x.group_id
    affected = [uid] if uid is not None else prov.group_members(db, gid)
    db.delete(x)
    db.flush()
    prov.on_assignment_change(db, a.id, affected, gid)
    record(db, AuditAction.APPLICATION_ASSIGNMENT_REMOVED, request, actor, a.id, "application", {"user_id": uid, "group_id": gid})
    db.commit()
    return {"success": True}


# ---- My apps (any signed-in user) --------------------------------------------------------------------------------

SAML_FACET = "saml"  # marker: the application has a SAML provider, launched through the UI continue page
SWA_FACET = "swa"  # marker: the application has an SWA form configuration, launched through the UI continue page


def _initiate_uri(db: Session, a: Application) -> Optional[str]:
    if a.sign_on_mode == "saml":
        return SAML_FACET if db.query(SamlProvider.id).filter(SamlProvider.application_id == a.id).first() else None
    if a.sign_on_mode == "swa":
        return SWA_FACET if db.query(SwaConfig.id).filter(SwaConfig.application_id == a.id).first() else None
    if a.sign_on_mode != "oidc":
        return None
    return db.query(OIDCClient.initiate_login_uri).filter(OIDCClient.application_id == a.id).scalar()


def _launchable(a: Application, initiate: Optional[str] = None) -> bool:
    return a.status == "active" and a.visible and a.sign_on_mode in ("bookmark", "oidc", "saml", "swa") and bool(a.launch_url or initiate)


def _launch_target(a: Application, initiate: Optional[str]) -> str:
    """Bookmarks open the URL. An OIDC app with an initiate-login URI gets OIDC "third-party initiated login" (Core 1.0
    section 4 of the OIDC Third Party Initiated Login spec): iss (+ target_link_uri); the app then starts a normal
    authorization-code flow with its own state and PKCE, so nothing sensitive is in the URL and no unsolicited response exists."""
    if a.sign_on_mode == "saml":
        from backend.app.saml.routes import ui_base

        return f"{ui_base()}/saml/continue?app={a.id}"
    if a.sign_on_mode == "swa":
        from backend.app.saml.routes import ui_base

        return f"{ui_base()}/swa/continue?app={a.id}"
    if a.sign_on_mode == "oidc" and initiate:
        q = {"iss": settings.OIDC_ISSUER}
        if a.launch_url:
            q["target_link_uri"] = a.launch_url
        return initiate + ("&" if "?" in initiate else "?") + urlencode(q)
    return a.launch_url or ""


@me_router.get("")
def my_apps(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ids = ent.entitled_application_ids(db, user.id)
    rows = db.query(Application).filter(Application.id.in_(ids or {0}), Application.status == "active", Application.visible.is_(True),
                                        Application.sign_on_mode != "none").order_by(Application.name).all()
    icons = {i for (i,) in db.query(ApplicationIcon.application_id).filter(ApplicationIcon.application_id.in_([a.id for a in rows] or [0])).all()}
    return {"items": [{"id": a.id, "name": a.name, "description": a.description, "sign_on_mode": a.sign_on_mode, "launchable": _launchable(a, _initiate_uri(db, a)),
                       "has_icon": a.id in icons} for a in rows]}


@me_router.post("/{app_id}/launch")
def launch(app_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    a = db.get(Application, app_id)
    initiate = _initiate_uri(db, a) if a is not None else None
    if a is None or not _launchable(a, initiate) or not ent.is_entitled(db, a.id, user.id):
        raise HTTPException(status_code=404, detail="Application not found")  # same answer whether it exists or not
    record(db, AuditAction.APPLICATION_LAUNCHED, request, user, a.id, "application", {"name": a.name})
    from backend.app.dashboard_prefs.routes import note_launch

    note_launch(db, user, a.id)
    db.commit()
    return {"url": _launch_target(a, initiate)}


@me_router.get("/{app_id}/icon")
def my_app_icon(app_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    a = db.get(Application, app_id)
    icon = db.get(ApplicationIcon, app_id) if a is not None else None
    if a is None or icon is None or a.status != "active" or not a.visible or not ent.is_entitled(db, a.id, user.id):
        raise HTTPException(status_code=404, detail="Not found")
    return _icon_response(icon)
