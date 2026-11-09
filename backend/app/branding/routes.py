"""Branding and email templates: a public read for the sign-in page, and admin editing (ADR 015)."""

import base64
import binascii
import hashlib
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from backend.app import mailer, ratelimit
from backend.app.applications.routes import _sniff
from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.auth.deps import require_admin
from backend.app.branding import templates as T
from backend.app.branding.models import EmailTemplate, OrgBranding, OrgLogo
from backend.app.db import get_db
from backend.app.users.model import User

public_router = APIRouter(prefix="/branding", tags=["branding"])
router = APIRouter(prefix="/admin/branding", tags=["branding"])
templates_router = APIRouter(prefix="/admin/email-templates", tags=["branding"])

MAX_LOGO_BYTES = 200 * 1024
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_CTRL = re.compile(r"[\x00-\x1f\x7f]")


def _now():
    return datetime.now(timezone.utc)


def _view(db: Session) -> dict:
    b = db.query(OrgBranding).first()
    logo = db.query(OrgLogo).first()
    return {
        "display_name": (b.display_name if b else None) or T.DEFAULT_ORG_NAME,
        "custom_name": bool(b and b.display_name),
        "primary_color": b.primary_color if b else None,
        "tagline": b.tagline if b else None,
        "has_logo": logo is not None,
        "logo_rev": logo.sha256[:12] if logo else None,
    }


@public_router.get("")
def public_branding(db: Session = Depends(get_db)):
    """Everything here is already visible to anyone who opens the sign-in page. No secrets, no user data."""
    return Response(content=__import__("json").dumps(_view(db)), media_type="application/json", headers={"Cache-Control": "no-cache"})


@public_router.get("/logo")
def public_logo(db: Session = Depends(get_db)):
    logo = db.query(OrgLogo).first()
    if logo is None:
        raise HTTPException(status_code=404, detail="No logo")
    return Response(content=logo.data, media_type=logo.content_type, headers={
        "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'; sandbox",
        "Cache-Control": "public, max-age=300", "ETag": f'"{logo.sha256[:32]}"', "Cross-Origin-Resource-Policy": "cross-origin"})


class BrandingBody(BaseModel):
    display_name: Optional[str] = Field(None, max_length=60)
    primary_color: Optional[str] = Field(None, max_length=7)
    tagline: Optional[str] = Field(None, max_length=160)

    @field_validator("display_name", "tagline")
    @classmethod
    def _text(cls, v):
        v = (v or "").strip()
        if _CTRL.search(v):
            raise ValueError("control characters are not allowed")
        return v or None

    @field_validator("primary_color")
    @classmethod
    def _color(cls, v):
        v = (v or "").strip()
        if not v:
            return None
        if not _HEX.match(v):
            raise ValueError("colour must look like #1a73e8")
        return v.lower()


@router.get("")
def get_branding(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return _view(db)


@router.put("")
def put_branding(body: BrandingBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    b = db.query(OrgBranding).first()
    if b is None:
        b = OrgBranding()
        db.add(b)
    b.display_name, b.primary_color, b.tagline, b.updated_at = body.display_name, body.primary_color, body.tagline, _now()
    record(db, AuditAction.BRANDING_UPDATED, request, actor, None, "branding",
           {"display_name": body.display_name, "primary_color": body.primary_color, "tagline": bool(body.tagline)})
    db.commit()
    return _view(db)


class LogoBody(BaseModel):
    data: str = Field(..., max_length=300_000)  # base64 of a PNG, JPEG or WebP


@router.put("/logo")
def put_logo(body: LogoBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    try:
        raw = base64.b64decode(body.data, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=422, detail="The logo is not valid base64")
    if not raw or len(raw) > MAX_LOGO_BYTES:
        raise HTTPException(status_code=422, detail=f"The logo must be at most {MAX_LOGO_BYTES // 1024} KB")
    ctype = _sniff(raw)
    if ctype is None:
        raise HTTPException(status_code=422, detail="The logo must be a PNG, JPEG or WebP image")
    digest = hashlib.sha256(raw).hexdigest()
    logo = db.query(OrgLogo).first()
    if logo is None:
        db.add(OrgLogo(content_type=ctype, data=raw, sha256=digest, updated_at=_now()))
    else:
        logo.content_type, logo.data, logo.sha256, logo.updated_at = ctype, raw, digest, _now()
    record(db, AuditAction.BRANDING_LOGO_SET, request, actor, None, "branding", {"bytes": len(raw), "type": ctype})
    db.commit()
    return _view(db)


@router.delete("/logo")
def delete_logo(request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    logo = db.query(OrgLogo).first()
    if logo is not None:
        db.delete(logo)
        record(db, AuditAction.BRANDING_LOGO_REMOVED, request, actor, None, "branding", {})
        db.commit()
    return _view(db)


# ---- email templates -------------------------------------------------------------------------------------------------

def _key(key: str) -> str:
    if key not in T.KEYS:
        raise HTTPException(status_code=404, detail="Unknown email template")
    return key


def _tpl(db: Session, key: str) -> dict:
    d = T.DEFAULTS[key]
    return {"key": key, "label": d["label"], **T.current(db, key), "default_subject": d["subject"], "default_body": d["body"], "variables": T.VARIABLES}


@templates_router.get("")
def list_templates(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return {"items": [_tpl(db, k) for k in T.KEYS], "mail_configured": mailer.configured()}


class TemplateBody(BaseModel):
    subject: str = Field(..., min_length=1, max_length=T.MAX_SUBJECT)
    body: str = Field(..., min_length=1, max_length=T.MAX_BODY)


def _check(b: TemplateBody) -> None:
    problem = T.validate(b.subject, b.body)
    if problem:
        raise HTTPException(status_code=422, detail=problem)


_SAMPLE = {"first_name": "Alex", "link": "https://example.invalid/set-password?token=SAMPLE", "valid_for": "24 hours"}


@templates_router.put("/{key}")
def put_template(key: str, body: TemplateBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    _key(key)
    _check(body)
    row = db.query(EmailTemplate).filter(EmailTemplate.key == key).first()
    if row is None:
        row = EmailTemplate(key=key, subject=body.subject, body=body.body, updated_at=_now())
        db.add(row)
    else:
        row.subject, row.body, row.updated_at = body.subject, body.body, _now()
    record(db, AuditAction.EMAIL_TEMPLATE_UPDATED, request, actor, None, "email_template", {"key": key})
    db.commit()
    return _tpl(db, key)


@templates_router.delete("/{key}")
def reset_template(key: str, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    _key(key)
    row = db.query(EmailTemplate).filter(EmailTemplate.key == key).first()
    if row is not None:
        db.delete(row)
        record(db, AuditAction.EMAIL_TEMPLATE_RESET, request, actor, None, "email_template", {"key": key})
        db.commit()
    return _tpl(db, key)


@templates_router.post("/{key}/preview")
def preview_template(key: str, body: TemplateBody, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    _key(key)
    _check(body)
    vals = {**_SAMPLE, "org_name": T.org_name(db)}
    return {"subject": T.render(body.subject, vals), "body": T.render(body.body, vals)}


@templates_router.post("/{key}/send-test")
def send_test(key: str, body: TemplateBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    """Sends the draft to the signed-in administrator's own address only, so this can never be used to mail anyone else."""
    _key(key)
    _check(body)
    if not mailer.configured():
        raise HTTPException(status_code=409, detail="Email is not configured on this server (SMTP_HOST and SMTP_FROM)")
    ratelimit.check("email_test", str(actor.id), 5)
    ratelimit.hit("email_test", str(actor.id), 3600)
    vals = {**_SAMPLE, "org_name": T.org_name(db), "first_name": actor.first_name}
    try:
        mailer.send(mailer.build(actor.email, "[Test] " + T.render(body.subject, vals), T.render(body.body, vals)), timeout=10)
    except Exception:  # noqa: BLE001 - delivery details stay out of the response
        raise HTTPException(status_code=502, detail="The test email could not be sent")
    record(db, AuditAction.EMAIL_TEST_SENT, request, actor, None, "email_template", {"key": key})
    db.commit()
    return {"sent_to": actor.email}
