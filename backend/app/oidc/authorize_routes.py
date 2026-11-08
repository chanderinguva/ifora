"""/oauth/authorize (browser redirect flow) and the small JSON API the consent page uses."""

from typing import Optional
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app import ratelimit
from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.auth.deps import get_session_and_user
from backend.app.config import settings
from backend.app.db import get_db
from backend.app.oidc import authorize as az
from backend.app.oidc.models import OIDCClient

public_router = APIRouter(tags=["oidc"])
api_router = APIRouter(prefix="/oidc", tags=["oidc"])
NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _err_redirect(redirect_uri: str, e: az.AuthzError, state: Optional[str]) -> RedirectResponse:
    url = az.redirect_with(redirect_uri, {"error": e.error, "error_description": e.description, "state": state})
    return RedirectResponse(url, status_code=303, headers=NO_STORE)


def _optional_session(request: Request, db: Session):
    try:
        return get_session_and_user(request, db)
    except HTTPException as e:
        if e.status_code == 401:
            return None
        raise


@public_router.get("/oauth/authorize")
def authorize(request: Request, db: Session = Depends(get_db)):
    ident = ratelimit.client_ip(request)  # every request parks a row or mints a code, so volume is capped per IP
    ratelimit.check("oauth_authorize", ident, settings.RATE_LIMIT_AUTHORIZE_REQUESTS)
    ratelimit.hit("oauth_authorize", ident, settings.RATE_LIMIT_AUTHORIZE_WINDOW_SECONDS)
    q = dict(request.query_params)
    if len(request.query_params.multi_items()) != len(q):  # RFC 6749 §3.1: parameters MUST NOT repeat
        return JSONResponse({"error": "invalid_request", "error_description": "repeated parameter"}, 400, headers=NO_STORE)
    try:
        p = az.validate_request(db, q)
    except az.ShownError as e:
        return JSONResponse({"error": "invalid_request", "error_description": str(e)}, 400, headers=NO_STORE)
    except az.AuthzError as e:
        # only raised after the client and redirect URI were proven genuine inside validate_request
        return _err_redirect(q["redirect_uri"], e, q.get("state"))

    ctx = _optional_session(request, db)
    prompt_none = bool(p.prompt and p.prompt == "none")
    reauth = az.needs_reauth(p, ctx[0] if ctx else None)
    if ctx is not None:
        session, user, _ = ctx
        from backend.app.applications.entitlement import sign_on_denied

        if sign_on_denied(db, p.client, user.id):
            return _err_redirect(p.redirect_uri, az.AuthzError("access_denied", "the user is not assigned to this application"), p.state)
        if reauth and prompt_none:
            return _err_redirect(p.redirect_uri, az.AuthzError("login_required", "re-authentication is required"), p.state)
        if not reauth and not az.consent_required(db, user.id, p.client, p.scopes, p.prompt):
            # Single sign-on: already authenticated and nothing to ask, so no UI hop.
            if p.client.first_party:
                az.record_consent(db, user.id, p.client, p.scopes, "first_party")
            code = az.mint_code(db, client=p.client, user_id=user.id, redirect_uri=p.redirect_uri, scopes=p.scopes,
                                nonce=p.nonce, code_challenge=p.code_challenge, auth_time=session.auth_time, amr=session.amr)
            db.commit()
            return RedirectResponse(az.redirect_with(p.redirect_uri, {"code": code, "state": p.state}), status_code=303, headers=NO_STORE)
        if prompt_none and not reauth:
            return _err_redirect(p.redirect_uri, az.AuthzError("consent_required", "consent is required"), p.state)
    elif prompt_none:
        return _err_redirect(p.redirect_uri, az.AuthzError("login_required", "the user is not signed in"), p.state)

    raw = az.park(db, p, auth_after=az.now() if reauth else None)
    db.commit()
    return RedirectResponse(f"{settings.OIDC_LOGIN_UI_URL}?{urlencode({'request_id': raw})}", status_code=303, headers=NO_STORE)


# ---- JSON API used by the consent page (cookie session + CSRF, like every other UI call) ----------------

def _view(db: Session, pending, user, session) -> dict:
    client = db.get(OIDCClient, pending.client_pk)
    return {
        "client": {"name": client.name, "description": client.description, "first_party": client.first_party},
        "scopes": [{"name": s, "description": az.SCOPE_DESCRIPTIONS[s]} for s in pending.scopes],
        "user": {"email": user.email},
        "reauth_required": bool(pending.auth_after and session.auth_time < pending.auth_after),
        "consent_required": az.consent_required(db, user.id, client, pending.scopes, pending.prompt),
        "redirect_host": urlsplit(pending.redirect_uri).netloc,
    }


@api_router.get("/authorization-requests/{request_id}")
def get_request(request_id: str, ctx=Depends(get_session_and_user), db: Session = Depends(get_db)):
    pending = az.peek_pending(db, request_id)
    if pending is None:
        raise HTTPException(status_code=404, detail="This sign-in request has expired. Return to the application and try again.")
    return JSONResponse(_view(db, pending, ctx[1], ctx[0]), headers=NO_STORE)


class Decision(BaseModel):
    approve: bool


@api_router.post("/authorization-requests/{request_id}/decision")
def decide(request_id: str, body: Decision, request: Request, ctx=Depends(get_session_and_user), db: Session = Depends(get_db)):
    session, user, _ = ctx
    peeked = az.peek_pending(db, request_id)
    if peeked is not None and peeked.auth_after and session.auth_time < peeked.auth_after:
        # the sign-in that existed when the request was made is not fresh enough; the request stays usable after re-login
        raise HTTPException(status_code=403, detail="reauthentication_required")
    pending = az.claim_pending(db, request_id)  # single use; a replay or an expired request gets nothing
    if pending is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="This sign-in request has expired. Return to the application and try again.")
    client = db.get(OIDCClient, pending.client_pk)
    if client is None or client.status != "active" or pending.redirect_uri not in client.redirect_uris:
        db.commit()  # the request stays consumed
        raise HTTPException(status_code=400, detail="This application is no longer available")

    from backend.app.applications.entitlement import sign_on_denied

    if sign_on_denied(db, client, user.id):
        db.commit()  # the request stays consumed
        url = az.redirect_with(pending.redirect_uri, {"error": "access_denied", "error_description": "the user is not assigned to this application", "state": pending.state})
        return JSONResponse({"redirect_to": url}, headers=NO_STORE)

    meta = {"client_id": client.client_id, "scopes": pending.scopes}
    if not body.approve:
        record(db, AuditAction.OIDC_CONSENT_DENIED, request, user, user.id, "user", meta)
        db.commit()
        url = az.redirect_with(pending.redirect_uri, {"error": "access_denied", "error_description": "the user denied the request", "state": pending.state})
        return JSONResponse({"redirect_to": url}, headers=NO_STORE)

    az.record_consent(db, user.id, client, pending.scopes, "first_party" if client.first_party else "user")
    if not client.first_party:
        record(db, AuditAction.OIDC_CONSENT_GRANTED, request, user, user.id, "user", meta)
    code = az.mint_code(db, client=client, user_id=user.id, redirect_uri=pending.redirect_uri, scopes=pending.scopes,
                        nonce=pending.nonce, code_challenge=pending.code_challenge, auth_time=session.auth_time, amr=session.amr)
    db.commit()
    url = az.redirect_with(pending.redirect_uri, {"code": code, "state": pending.state})
    return JSONResponse({"redirect_to": url}, headers=NO_STORE)
