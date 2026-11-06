"""Passkeys (WebAuthn): usernameless sign-in, self-service management, 'passkey required' policy."""

from typing import Any, Dict

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app import ratelimit
from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.auth import passkey_service as svc
from backend.app.auth.deps import check_origin, get_session_and_user
from backend.app.auth.passkey_model import Passkey
from backend.app.auth.routes import complete_login
from backend.app.auth.sessions_util import revoke_user_sessions
from backend.app.config import settings
from backend.app.db import get_db
from backend.app.users.model import User

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["passkeys"])

MIN_PASSKEYS_FOR_POLICY = 2  # one lost device must not lock the owner out


class PasswordOnly(BaseModel):
    password: str = Field(..., max_length=128)


class RegisterVerify(BaseModel):
    ceremony_id: str = Field(..., max_length=128)
    credential: Dict[str, Any]
    name: str = Field("Passkey", min_length=1, max_length=100)


class LoginVerify(BaseModel):
    ceremony_id: str = Field(..., max_length=128)
    credential: Dict[str, Any]


class Rename(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class RemoveBody(BaseModel):
    password: str = Field(..., max_length=128)


class PolicyBody(BaseModel):
    password: str = Field(..., max_length=128)
    require: bool


def _reauth(user: User, password: str) -> None:
    if not user.verify_password(password):
        raise HTTPException(status_code=403, detail="Password is incorrect")


def _own(db: Session, user: User, passkey_id: int) -> Passkey:
    p = db.query(Passkey).filter(Passkey.id == passkey_id, Passkey.user_id == user.id).first()
    if p is None:  # also covers other users' ids: no existence oracle
        raise HTTPException(status_code=404, detail="Passkey not found")
    return p


# ---- sign in with a passkey (unauthenticated) ---------------------------------------

@router.post("/login/passkey/options")
def login_options(request: Request, db: Session = Depends(get_db)):
    check_origin(request)
    ratelimit.check("login", ratelimit.client_ip(request), settings.RATE_LIMIT_LOGIN_FAILURES)
    ceremony, options = svc.authentication_options(db)
    return {"ceremony_id": ceremony, "options": options}


@router.post("/login/passkey/verify")
async def login_verify(request: Request, response: Response, body: LoginVerify, db: Session = Depends(get_db)):
    check_origin(request)
    ip = ratelimit.client_ip(request)
    ratelimit.check("login", ip, settings.RATE_LIMIT_LOGIN_FAILURES)
    failed = HTTPException(status_code=401, detail="Passkey sign-in failed")

    def fail(reason: str, user: User | None = None) -> HTTPException:
        ratelimit.hit("login", ip, settings.RATE_LIMIT_LOGIN_WINDOW_SECONDS)
        action = AuditAction.PASSKEY_COUNTER_ANOMALY if reason == "counter_rollback" else AuditAction.PASSKEY_LOGIN_FAILED
        record(db, action, request, user, user.id if user else None, "user", {"reason": reason})
        db.commit()
        logger.warning("passkey.login_failed", reason=reason, user_id=user.id if user else None)
        return failed

    challenge = svc.consume(db, body.ceremony_id, "login")
    if challenge is None:
        raise fail("bad_ceremony")
    try:
        user, passkey = svc.verify_authentication(db, challenge, body.credential)
    except svc.AuthFailure as e:
        raise fail(e.reason, e.user)
    if user.status != "active":
        db.rollback()
        raise fail("inactive", user)
    db.commit()  # persist counter / last_used
    return await complete_login(db, request, response, user, method="passkey")


# ---- self-service ---------------------------------------------------------------------

@router.get("/me/passkeys")
def list_passkeys(ctx=Depends(get_session_and_user)):
    user = ctx[1]
    return {
        "items": [p.to_dict() for p in user.passkeys],
        "require_passkey": user.passkey_required,
        "min_for_policy": MIN_PASSKEYS_FOR_POLICY,
    }


@router.post("/me/passkeys/register/options")
def register_options(body: PasswordOnly, ctx=Depends(get_session_and_user), db: Session = Depends(get_db)):
    user = ctx[1]
    _reauth(user, body.password)
    if len(user.passkeys) >= 10:
        raise HTTPException(status_code=400, detail="Passkey limit reached")
    ceremony, options = svc.registration_options(db, user)
    db.commit()
    return {"ceremony_id": ceremony, "options": options}


@router.post("/me/passkeys/register/verify", status_code=201)
def register_verify(
    body: RegisterVerify, request: Request, ctx=Depends(get_session_and_user), db: Session = Depends(get_db)
):
    user = ctx[1]
    challenge = svc.consume(db, body.ceremony_id, "register", user.id)
    if challenge is None:
        raise HTTPException(status_code=400, detail="Registration expired. Start again.")
    try:
        passkey = svc.verify_registration(db, user, challenge, body.credential, body.name.strip() or "Passkey")
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.warning("passkey.register_failed", user_id=user.id, error=str(e))
        raise HTTPException(status_code=400, detail="Passkey could not be verified")
    db.flush()
    record(db, AuditAction.PASSKEY_REGISTERED, request, user, user.id, "user", {"passkey_id": passkey.id, "name": passkey.name})
    db.commit()
    db.refresh(passkey)
    return passkey.to_dict()


@router.patch("/me/passkeys/{passkey_id}")
def rename_passkey(
    passkey_id: int, body: Rename, request: Request, ctx=Depends(get_session_and_user), db: Session = Depends(get_db)
):
    user = ctx[1]
    p = _own(db, user, passkey_id)
    p.name = body.name.strip() or p.name
    record(db, AuditAction.PASSKEY_RENAMED, request, user, user.id, "user", {"passkey_id": p.id})
    db.commit()
    return p.to_dict()


@router.post("/me/passkeys/{passkey_id}/remove")
def remove_passkey(
    passkey_id: int, body: RemoveBody, request: Request, ctx=Depends(get_session_and_user), db: Session = Depends(get_db)
):
    user = ctx[1]
    _reauth(user, body.password)
    p = _own(db, user, passkey_id)
    if user.passkey_required and len(user.passkeys) <= MIN_PASSKEYS_FOR_POLICY:
        raise HTTPException(
            status_code=409,
            detail=f"Turn off 'require a passkey' first: at least {MIN_PASSKEYS_FOR_POLICY} passkeys are needed while it is on",
        )
    db.delete(p)
    record(db, AuditAction.PASSKEY_REMOVED, request, user, user.id, "user", {"passkey_id": passkey_id})
    db.commit()
    return {"success": True}


@router.post("/me/passkeys/policy")
def set_policy(body: PolicyBody, request: Request, ctx=Depends(get_session_and_user), db: Session = Depends(get_db)):
    """'Require a passkey to sign in': password sign-in is refused for this account."""
    session, user, _ = ctx
    _reauth(user, body.password)
    if body.require and len(user.passkeys) < MIN_PASSKEYS_FOR_POLICY:
        raise HTTPException(
            status_code=409,
            detail=f"Register at least {MIN_PASSKEYS_FOR_POLICY} passkeys first so losing one device cannot lock you out",
        )
    user.passkey_required = body.require
    revoked = revoke_user_sessions(db, user.id, except_id=session.id) if body.require else 0
    record(db, AuditAction.PASSKEY_POLICY_CHANGED, request, user, user.id, "user", {"require": body.require, "other_sessions_revoked": revoked})
    db.commit()
    return {"require_passkey": user.passkey_required}
