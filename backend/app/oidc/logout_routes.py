"""/oauth/logout (browser entry) and the JSON API the logout confirmation page uses."""

from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.auth.deps import clear_session_cookie, get_session_and_user
from backend.app.config import settings
from backend.app.db import get_db
from backend.app.oidc import logout as lo
from backend.app.oidc import refresh

public_router = APIRouter(tags=["oidc"])
api_router = APIRouter(prefix="/oidc", tags=["oidc"])
NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _optional_session(request: Request, db: Session):
    try:
        return get_session_and_user(request, db)  # also enforces Origin + CSRF on POST when a session exists
    except HTTPException as e:
        if e.status_code == 401:
            return None
        raise


@public_router.api_route("/oauth/logout", methods=["GET", "POST"])
async def logout_entry(request: Request):
    """Hand the browser to the confirmation page with only the parameters we understand."""
    data = dict(request.query_params)
    if request.method == "POST":
        data.update({k: v for k, v in (await request.form()).items() if isinstance(v, str)})
    keep = {k: data[k] for k in lo.PARAMS if k in data and len(data[k]) <= lo.MAX}
    return RedirectResponse(f"{settings.OIDC_LOGOUT_UI_URL}?{urlencode(keep)}", status_code=303, headers=NO_STORE)


@api_router.get("/logout-request")
def logout_request(request: Request, db: Session = Depends(get_db)):
    plan = lo.resolve(db, dict(request.query_params))
    ctx = _optional_session(request, db)
    return JSONResponse({
        "client_name": plan.client.name if plan.client else None,
        "will_redirect": plan.redirect_uri is not None,
        "signed_in_as": ctx[1].email if ctx else None,
    }, headers=NO_STORE)


class LogoutBody(BaseModel):
    id_token_hint: Optional[str] = None
    post_logout_redirect_uri: Optional[str] = None
    state: Optional[str] = None
    client_id: Optional[str] = None


@api_router.post("/logout")
def logout(body: LogoutBody, request: Request, db: Session = Depends(get_db)):
    plan = lo.resolve(db, body.model_dump(exclude_none=True))
    ctx = _optional_session(request, db)
    redirect = lo.redirect_url(plan)
    if ctx is not None:
        session, user, _ = ctx
        if plan.sub is not None and plan.sub != user.public_id:
            redirect = None  # the hint names someone else: still sign out, but do not bounce into the RP as if it matched
        session.revoke()
        revoked = 0
        if plan.client is not None and (plan.sub is None or plan.sub == user.public_id):
            # The user confirmed leaving this application (IFORA-24): its refresh tokens end with the session, so the
            # application cannot keep minting tokens for someone who signed out. Other applications are untouched.
            revoked = refresh.revoke_for_user_client(db, user.id, plan.client.id)
        record(db, AuditAction.OIDC_LOGOUT, request, user, user.id, "user",
               {"client_id": plan.client.client_id if plan.client else None, "refresh_tokens_revoked": revoked})
        db.commit()
    out = JSONResponse({"redirect_to": redirect}, headers=NO_STORE)
    if ctx is not None:
        clear_session_cookie(out)
    return out
