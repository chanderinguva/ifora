"""End-user dashboard: sections, favourites, recently used, own sign-in activity (ADR 016).

Everything is keyed to the signed-in user and gated by entitlement: a preference never makes an
application visible, and preferences for applications the user can no longer see are ignored.
"""

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.applications import entitlement as ent
from backend.app.applications.models import Application
from backend.app.audit.model import AuditAction, AuditEvent
from backend.app.auth.deps import get_current_user
from backend.app.dashboard_prefs.models import UserAppPref, UserAppSection
from backend.app.db import get_db
from backend.app.users.model import User

router = APIRouter(prefix="/me/dashboard", tags=["dashboard"])
MAX_SECTIONS = 10
RECENT_DAYS = 30
RECENT_LIMIT = 6
ACTIVITY_ACTIONS = [AuditAction.LOGIN_SUCCESS, AuditAction.LOGIN_FAILURE, AuditAction.LOGOUT, AuditAction.USER_PASSWORD_CHANGED,
                    AuditAction.PASSWORD_RESET_COMPLETED, AuditAction.MFA_ENABLED, AuditAction.MFA_DISABLED, AuditAction.MFA_RESET,
                    AuditAction.MFA_RECOVERY_USED, AuditAction.PASSKEY_REGISTERED, AuditAction.PASSKEY_REMOVED]


def _visible_ids(db: Session, user: User) -> set:
    ids = ent.entitled_application_ids(db, user.id)
    if not ids:
        return set()
    return {i for (i,) in db.query(Application.id).filter(Application.id.in_(ids), Application.status == "active", Application.visible.is_(True),
                                                           Application.sign_on_mode != "none").all()}


def _pref(db: Session, user: User, app_id: int) -> UserAppPref:
    p = db.query(UserAppPref).filter(UserAppPref.user_id == user.id, UserAppPref.application_id == app_id).first()
    if p is None:
        p = UserAppPref(user_id=user.id, application_id=app_id, favorite=False, position=0, launch_count=0)
        db.add(p)
    return p


def _section(db: Session, user: User, section_id: int) -> UserAppSection:
    s = db.get(UserAppSection, section_id)
    if s is None or s.user_id != user.id:
        raise HTTPException(status_code=404, detail="Section not found")  # same answer for someone else's section
    return s


def _name(v: str) -> str:
    v = " ".join(v.split())
    if not v or any(ord(c) < 32 for c in v):
        raise HTTPException(status_code=422, detail="Section name is required")
    return v[:40]


@router.get("")
def overview(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    visible = _visible_ids(db, user)
    sections = db.query(UserAppSection).filter(UserAppSection.user_id == user.id).order_by(UserAppSection.position, UserAppSection.id).all()
    prefs = {p.application_id: p for p in db.query(UserAppPref).filter(UserAppPref.user_id == user.id).all() if p.application_id in visible}
    sec_ids = {s.id for s in sections}
    cutoff = datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)
    recent = sorted((p for p in prefs.values() if p.last_launched_at and p.last_launched_at >= cutoff), key=lambda p: p.last_launched_at, reverse=True)[:RECENT_LIMIT]
    return {
        "sections": [{"id": s.id, "name": s.name, "position": s.position} for s in sections],
        "apps": {str(i): {"favorite": p.favorite, "section_id": p.section_id if p.section_id in sec_ids else None, "position": p.position,
                          "last_launched_at": p.last_launched_at.isoformat() if p.last_launched_at else None} for i, p in prefs.items()},
        "recent": [p.application_id for p in recent],
    }


class SectionBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)


@router.post("/sections", status_code=201)
def create_section(body: SectionBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(UserAppSection).filter(UserAppSection.user_id == user.id).all()
    if len(rows) >= MAX_SECTIONS:
        raise HTTPException(status_code=409, detail=f"You can have at most {MAX_SECTIONS} sections")
    s = UserAppSection(user_id=user.id, name=_name(body.name), position=max((r.position for r in rows), default=-1) + 1)
    db.add(s)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="You already have a section with that name")
    return {"id": s.id, "name": s.name, "position": s.position}


class SectionPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=80)
    move: Optional[str] = Field(None, pattern="^(earlier|later)$")


@router.patch("/sections/{section_id}")
def update_section(section_id: int, body: SectionPatch, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    s = _section(db, user, section_id)
    if body.name is not None:
        s.name = _name(body.name)
    if body.move:
        rows = db.query(UserAppSection).filter(UserAppSection.user_id == user.id).order_by(UserAppSection.position, UserAppSection.id).all()
        i = next(k for k, r in enumerate(rows) if r.id == s.id)
        j = i - 1 if body.move == "earlier" else i + 1
        if 0 <= j < len(rows):
            rows[i], rows[j] = rows[j], rows[i]
        for k, r in enumerate(rows):
            r.position = k
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="You already have a section with that name")
    return {"id": s.id, "name": s.name, "position": s.position}


@router.delete("/sections/{section_id}", status_code=204)
def delete_section(section_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    s = _section(db, user, section_id)
    db.query(UserAppPref).filter(UserAppPref.section_id == s.id).update({UserAppPref.section_id: None})  # apps fall back to "Other"
    db.delete(s)
    db.commit()


class AppPatch(BaseModel):
    favorite: Optional[bool] = None
    section_id: Optional[int] = None
    clear_section: bool = False
    move: Optional[str] = Field(None, pattern="^(earlier|later)$")


@router.put("/apps/{app_id}")
def set_app(app_id: int, body: AppPatch, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    visible = _visible_ids(db, user)
    if app_id not in visible:
        raise HTTPException(status_code=404, detail="Application not found")
    p = _pref(db, user, app_id)
    if body.favorite is not None:
        p.favorite = body.favorite
    if body.clear_section:
        p.section_id = None
    elif body.section_id is not None:
        p.section_id = _section(db, user, body.section_id).id
    db.flush()
    if body.move:
        group = [q for q in db.query(UserAppPref).filter(UserAppPref.user_id == user.id, UserAppPref.section_id == p.section_id).all() if q.application_id in visible]
        names = {a.id: a.name.lower() for a in db.query(Application).filter(Application.id.in_([q.application_id for q in group] or [0])).all()}
        group.sort(key=lambda q: (q.position, names.get(q.application_id, "")))
        i = group.index(p)
        j = i - 1 if body.move == "earlier" else i + 1
        if 0 <= j < len(group):
            group[i], group[j] = group[j], group[i]
        for k, q in enumerate(group):
            q.position = k
    db.commit()
    return {"favorite": p.favorite, "section_id": p.section_id, "position": p.position}


class ImportBody(BaseModel):
    app_ids: List[int] = Field(default_factory=list, max_length=200)


@router.post("/import-favorites")
def import_favorites(body: ImportBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """One-time move of the old browser-only pins; ids the user cannot see are skipped."""
    visible = _visible_ids(db, user)
    n = 0
    for i in set(body.app_ids) & visible:
        p = _pref(db, user, i)
        if not p.favorite:
            p.favorite = True
            n += 1
    db.commit()
    return {"imported": n}


@router.get("/activity")
def activity(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """The signed-in user's own security-relevant events. Never other people's, never admin actions on others."""
    uid = str(user.id)
    rows = (db.query(AuditEvent)
            .filter(AuditEvent.action.in_([a.value for a in ACTIVITY_ACTIONS]),
                    or_(AuditEvent.actor_id == uid, (AuditEvent.target_type == "user") & (AuditEvent.target_id == uid)))
            .order_by(AuditEvent.timestamp.desc(), AuditEvent.id.desc()).limit(15).all())
    return {"items": [{"id": e.id, "action": e.action, "timestamp": e.timestamp.isoformat(), "ip": e.actor_ip_address} for e in rows]}


def note_launch(db: Session, user: User, app_id: int) -> None:
    """Called from the launch endpoint (same transaction) once entitlement is already proven."""
    p = _pref(db, user, app_id)
    p.last_launched_at = datetime.now(timezone.utc)
    p.launch_count = (p.launch_count or 0) + 1
