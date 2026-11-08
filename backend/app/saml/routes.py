"""SAML 2.0 identity provider endpoints (ADR 011).

SP-initiated:  SP -> GET/POST /saml/sso  -> park the request -> UI /saml/continue (sign in) -> POST /api/v1/saml/requests/{id}/respond
               -> the UI auto-posts the signed response to the SP's registered ACS.
IdP-initiated: My apps tile -> UI /saml/continue?app=ID -> POST /api/v1/me/apps/{id}/saml-response -> same auto-post.
An assertion is only ever produced for the signed-in, entitled user and only addressed to the ACS registered by an administrator.
"""

import base64
import binascii
import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app import ratelimit
from backend.app.applications.entitlement import application_denied
from backend.app.applications.models import Application
from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.auth.deps import get_current_user, get_session_and_user, require_admin
from backend.app.config import settings
from backend.app.db import get_db
from backend.app.oidc import clients as oidc_clients
from backend.app.saml import keys, protocol as P
from backend.app.saml.models import SamlPendingRequest, SamlProvider
from backend.app.users.model import User

public_router = APIRouter(tags=["saml"])
api_router = APIRouter(prefix="/saml", tags=["saml"])
admin_router = APIRouter(prefix="/admin/applications", tags=["saml"])
NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}

SOURCES = {"email", "username", "first_name", "last_name", "display_name", "groups"}
_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.:/\-]{0,127}$")
_ATTR_KEY = re.compile(r"^attr:[A-Za-z0-9_.\-]{1,64}$")
MAX_MAPPINGS = 30
ACR_PPT = "urn:oasis:names:tc:SAML:2.0:ac:classes:PasswordProtectedTransport"
ACR_MFA = "urn:oasis:names:tc:SAML:2.0:ac:classes:MobileTwoFactorContract"
DEFAULT_MAPPINGS = [{"name": "email", "source": "email"}, {"name": "firstName", "source": "first_name"}, {"name": "lastName", "source": "last_name"}]


def ui_base() -> str:
    u = urlsplit(settings.OIDC_LOGIN_UI_URL)
    return f"{u.scheme}://{u.netloc}"


def _h(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---- attributes -------------------------------------------------------------------------------------------------

FILTERS = ("equals", "starts_with", "contains")
MAX_EXPR = 300


_USER_FIELDS = {"email", "username", "first_name", "last_name", "status"}


def _el_lookup(user: User, attribute: str):
    """What `user.<attr>` reads inside an attribute expression. Unlike group rules, names are readable here: the value only goes
    into the assertion, it does not grant access inside IdentityForge."""
    v = getattr(user, attribute, None) if attribute in _USER_FIELDS else user.get_profile_attributes().get(attribute)
    return None if v == "" else v


def attribute_values(user: User, source: str, flt: Optional[dict] = None) -> List[str]:
    """Values for one mapping. `source` is a fixed field, `attr:<profile key>`, or `expr:<expression>` (Okta EL subset, no eval)."""
    if source == "email":
        return [user.email]
    if source == "username":
        return [user.username]
    if source == "first_name":
        return [user.first_name]
    if source == "last_name":
        return [user.last_name]
    if source == "display_name":
        return [f"{user.first_name} {user.last_name}".strip()]
    if source == "groups":
        names = sorted(g.name for g in user.groups)
        if flt:
            want, kind = flt["value"].lower(), flt["type"]
            names = [n for n in names if (n.lower() == want if kind == "equals" else n.lower().startswith(want) if kind == "starts_with" else want in n.lower())]
        return names
    if source.startswith("attr:"):
        v = user.get_profile_attributes().get(source[5:])
        return [] if v in (None, "") else [str(v)]
    if source.startswith("expr:"):
        from backend.app.groups import okta_el

        try:
            v = okta_el.evaluate(okta_el.parse(source[5:]), lambda a: _el_lookup(user, a))
        except okta_el.ElError:
            return []  # a runtime problem means "no value" (and fails a required attribute) rather than a wrong value
        return [] if v is None or v == "" else [str(v).lower() if isinstance(v, bool) else str(v)[:1000]]
    return []


def resolve_attributes(user: User, mappings: List[dict]):
    """(attributes, missing_required_names)."""
    out, missing = [], []
    for m in mappings:
        vals = attribute_values(user, m["source"], m.get("filter"))
        if vals:
            out.append((m["name"], vals))
        elif m.get("required"):
            missing.append(m["name"])
    return out, missing


def name_id_value(p: "SamlProvider", user: User) -> Optional[str]:
    f = p.name_id_format
    if f == "email":
        return user.email
    if f == "persistent":
        return P.persistent_name_id(p.sp_entity_id, user.id)
    if f == "username":
        return user.username
    v = attribute_values(user, p.name_id_attribute or "")  # "attribute"
    return v[0] if v else None


def _checked_mappings(items: List[dict]) -> List[dict]:
    from backend.app.groups import okta_el

    if len(items) > MAX_MAPPINGS:
        raise HTTPException(status_code=422, detail=f"At most {MAX_MAPPINGS} attributes")
    seen, out = set(), []
    for m in items:
        name, src = (m.get("name") or "").strip(), (m.get("source") or "").strip()
        if not _NAME.match(name):
            raise HTTPException(status_code=422, detail=f"Invalid attribute name: {name!r}")
        if name in seen:
            raise HTTPException(status_code=422, detail=f"Duplicate attribute name: {name}")
        seen.add(name)
        item = {"name": name, "source": src}
        if src.startswith("expr:"):
            text = src[5:].strip()
            if not text or len(text) > MAX_EXPR:
                raise HTTPException(status_code=422, detail=f"Expression for {name} must be 1–{MAX_EXPR} characters")
            try:
                okta_el.evaluate(okta_el.parse(text), lambda a: "sample")  # syntax and function/argument errors surface now
            except okta_el.ElError as e:
                raise HTTPException(status_code=422, detail=f"Expression for {name}: {e}")
            item["source"] = "expr:" + text
        elif src not in SOURCES and not _ATTR_KEY.match(src):
            raise HTTPException(status_code=422, detail=f"Unknown attribute source: {src!r}")
        flt = m.get("filter")
        if flt:
            if src != "groups":
                raise HTTPException(status_code=422, detail="A filter applies to the groups attribute only")
            if flt.get("type") not in FILTERS or not str(flt.get("value", "")).strip() or len(str(flt["value"])) > 100:
                raise HTTPException(status_code=422, detail=f"Group filter must be one of {', '.join(FILTERS)} with a value")
            item["filter"] = {"type": flt["type"], "value": str(flt["value"]).strip()}
        if m.get("required"):
            item["required"] = True
        out.append(item)
    return out


# ---- issuing ----------------------------------------------------------------------------------------------------

NAME_ID_URN = {"email": P.FMT_EMAIL, "persistent": P.FMT_PERSISTENT, "username": P.FMT_UNSPECIFIED, "attribute": P.FMT_UNSPECIFIED}


class MissingAttributes(Exception):
    def __init__(self, names: List[str]):
        self.names = names


def issue(db: Session, p: SamlProvider, user: User, session, in_response_to: Optional[str]) -> bytes:
    key_pem, cert_pem = keys.private_and_cert(keys.active(db))
    name_id = name_id_value(p, user)
    attrs, missing = resolve_attributes(user, p.attribute_mappings)
    if not name_id:
        missing.insert(0, "NameID")
    if missing:
        raise MissingAttributes(missing)
    return P.build_response(
        sp_entity_id=p.sp_entity_id, acs_url=p.acs_url, audience=p.audience or p.sp_entity_id, name_id=name_id,
        name_id_format=NAME_ID_URN[p.name_id_format], in_response_to=in_response_to, attributes=attrs,
        auth_time=session.auth_time, authn_context=ACR_MFA if "mfa" in (session.amr or []) else ACR_PPT,
        validity=p.validity_seconds, sign_assertion=p.signing in ("assertion", "both"), sign_response=p.signing in ("response", "both"),
        key_pem=key_pem, cert_pem=cert_pem)


def _provider_app(db: Session, p: SamlProvider) -> Application:
    a = db.get(Application, p.application_id)
    if a is None or a.sign_on_mode != "saml":
        raise HTTPException(status_code=404, detail="This application is not available")
    return a


def _respond(db: Session, request: Request, p: SamlProvider, user: User, session, in_response_to: Optional[str], relay: Optional[str]) -> dict:
    a = _provider_app(db, p)
    if application_denied(db, a, user.id):
        record(db, AuditAction.APPLICATION_SAML_SSO, request, user, a.id, "application", {"name": a.name, "result": "denied"})
        db.commit()
        raise HTTPException(status_code=403, detail="You are not assigned to this application")
    from backend.app.policies import engine as policy

    pd = policy.check(db, request, a.id, user, session)
    if pd.kind != policy.ALLOW:
        db.commit()  # keeps the policy-denied audit row
        raise HTTPException(status_code=403, detail="reauthentication_required" if pd.kind == policy.REAUTH else pd.reason)
    try:
        xml = issue(db, p, user, session, in_response_to)
    except MissingAttributes as e:
        record(db, AuditAction.APPLICATION_SAML_SSO, request, user, a.id, "application", {"name": a.name, "result": "missing_attributes", "missing": e.names})
        db.commit()
        raise HTTPException(status_code=409, detail="Your profile is missing information this application requires: " + ", ".join(e.names) + ". Ask an administrator to complete it.")
    record(db, AuditAction.APPLICATION_SAML_SSO, request, user, a.id, "application",
           {"name": a.name, "sp": p.sp_entity_id, "initiated_by": "sp" if in_response_to else "idp", "result": "issued"})
    db.commit()
    return {"acs_url": p.acs_url, "saml_response": base64.b64encode(xml).decode(), "relay_state": relay if relay is not None else p.default_relay_state}


# ---- public: metadata and SSO endpoint -------------------------------------------------------------------------

@public_router.get("/saml/metadata")
def metadata(db: Session = Depends(get_db)):
    xml = P.idp_metadata(keys.published_certs(db))
    db.commit()  # the first call creates the signing key
    return Response(xml, media_type="application/samlmetadata+xml", headers={"Cache-Control": "public, max-age=300"})


def _error_redirect(msg: str) -> RedirectResponse:
    return RedirectResponse(f"{ui_base()}/saml/continue?{urlencode({'error': msg})}", status_code=303, headers=NO_STORE)


def _start(db: Session, request: Request, saml_request: Optional[str], relay_state: Optional[str], redirect_binding: bool):
    ident = ratelimit.client_ip(request)
    ratelimit.check("saml_sso", ident, settings.RATE_LIMIT_AUTHORIZE_REQUESTS)
    ratelimit.hit("saml_sso", ident, settings.RATE_LIMIT_AUTHORIZE_WINDOW_SECONDS)
    try:
        if not saml_request or len(saml_request) > 400_000:
            raise P.SamlError("Missing SAMLRequest")
        if relay_state is not None and len(relay_state.encode()) > 512:
            raise P.SamlError("RelayState is too long")
        try:
            raw = base64.b64decode(saml_request, validate=True)
        except (binascii.Error, ValueError):
            raise P.SamlError("The SAMLRequest is not valid base64")
        if redirect_binding:
            try:
                raw = P.inflate(raw)
            except Exception as e:
                raise P.SamlError(str(e) if isinstance(e, P.SamlError) else "The SAMLRequest could not be decoded")
        req = P.parse_authn_request(raw)
        p = db.query(SamlProvider).filter(SamlProvider.sp_entity_id == req.issuer).first()
        if p is None:
            raise P.SamlError("Unknown service provider")
        a = _provider_app(db, p)
        if a.status != "active":
            raise P.SamlError("This application is not available")
        if req.acs_url and req.acs_url != p.acs_url:
            raise P.SamlError("The request names an AssertionConsumerServiceURL that is not registered")
        signed = (redirect_binding and "Signature=" in request.url.query) or (not redirect_binding and P.is_signed(req.root))
        if p.require_signed_requests and not signed:
            raise P.SamlError("This application requires signed requests")
        if signed and p.sp_cert:
            if redirect_binding:
                P.verify_redirect_signature(request.url.query, p.sp_cert)
            else:
                P.verify_post_signature(req.root, p.sp_cert)
        elif p.require_signed_requests:
            raise P.SamlError("No certificate is registered to verify the request")
    except P.SamlError as e:
        return _error_redirect(str(e))

    rawid = secrets.token_urlsafe(32)
    db.add(SamlPendingRequest(request_hash=_h(rawid), provider_id=p.id, in_response_to=req.id, relay_state=relay_state,
                              auth_after=_now() if req.force_authn else None,
                              expires_at=_now() + timedelta(seconds=settings.SAML_PENDING_TTL_SECONDS)))
    db.commit()
    return RedirectResponse(f"{ui_base()}/saml/continue?{urlencode({'request_id': rawid})}", status_code=303, headers=NO_STORE)


@public_router.get("/saml/sso")
def sso_redirect(request: Request, db: Session = Depends(get_db)):
    q = request.query_params
    if len(q.multi_items()) != len(dict(q)):
        return _error_redirect("Repeated parameter")
    return _start(db, request, q.get("SAMLRequest"), q.get("RelayState"), True)


@public_router.post("/saml/sso")
def sso_post(request: Request, SAMLRequest: Optional[str] = Form(None), RelayState: Optional[str] = Form(None), db: Session = Depends(get_db)):
    return _start(db, request, SAMLRequest, RelayState, False)


# ---- JSON API used by the continue page -------------------------------------------------------------------------

def _peek(db: Session, raw: str) -> Optional[SamlPendingRequest]:
    if not raw or len(raw) > 128:
        return None
    r = db.query(SamlPendingRequest).filter(SamlPendingRequest.request_hash == _h(raw)).first()
    return None if r is None or r.decided_at is not None or r.expires_at <= _now() else r


def _policy_reauth(db: Session, request: Request, a, user, session) -> bool:
    from backend.app.policies import engine as policy

    return a is not None and policy.wants_reauth(db, request, a.id, user, session)


@api_router.get("/requests/{request_id}")
def get_request(request_id: str, request: Request, ctx=Depends(get_session_and_user), db: Session = Depends(get_db)):
    pending = _peek(db, request_id)
    if pending is None:
        raise HTTPException(status_code=404, detail="This sign-in request has expired. Return to the application and try again.")
    session, user, _ = ctx
    p = db.get(SamlProvider, pending.provider_id)
    a = db.get(Application, p.application_id)
    return {"application": a.name if a else "", "user": {"email": user.email},
            "reauth_required": bool(pending.auth_after and session.auth_time < pending.auth_after) or _policy_reauth(db, request, a, user, session)}


@api_router.post("/requests/{request_id}/respond")
def respond(request_id: str, request: Request, ctx=Depends(get_session_and_user), db: Session = Depends(get_db)):
    session, user, _ = ctx
    peeked = _peek(db, request_id)
    if peeked is not None and peeked.auth_after and session.auth_time < peeked.auth_after:
        raise HTTPException(status_code=403, detail="reauthentication_required")
    if peeked is not None:
        pp = db.get(SamlProvider, peeked.provider_id)
        if pp is not None and _policy_reauth(db, request, db.get(Application, pp.application_id), user, session):
            raise HTTPException(status_code=403, detail="reauthentication_required")  # nothing consumed; retry after sign-in
    n = db.execute(update(SamlPendingRequest).where(SamlPendingRequest.request_hash == _h(request_id), SamlPendingRequest.decided_at.is_(None),
                                                     SamlPendingRequest.expires_at > _now()).values(decided_at=_now())).rowcount
    if peeked is None or n != 1:  # single use: a replay or an expired request gets nothing
        db.rollback()
        raise HTTPException(status_code=404, detail="This sign-in request has expired. Return to the application and try again.")
    p = db.get(SamlProvider, peeked.provider_id)
    return _respond(db, request, p, user, session, peeked.in_response_to, peeked.relay_state)


@api_router.post("/apps/{app_id}/respond")
def idp_initiated(app_id: int, request: Request, ctx=Depends(get_session_and_user), db: Session = Depends(get_db)):
    session, user, _ = ctx
    p = db.query(SamlProvider).filter(SamlProvider.application_id == app_id).first()
    a = db.get(Application, app_id)
    if p is None or a is None or a.sign_on_mode != "saml" or not a.visible:
        raise HTTPException(status_code=404, detail="Application not found")  # same answer whether it exists or not
    return _respond(db, request, p, user, session, None, None)


# ---- admin ------------------------------------------------------------------------------------------------------

class SamlBody(BaseModel):
    sp_entity_id: str = Field(..., min_length=1, max_length=500)
    acs_url: str = Field(..., min_length=1, max_length=2000)
    audience: Optional[str] = Field(None, max_length=500)
    name_id_format: str = Field("email", pattern="^(email|persistent|username|attribute)$")
    name_id_attribute: Optional[str] = Field(None, max_length=80)  # for name_id_format = attribute: attr:<profile key>
    signing: str = Field("both", pattern="^(assertion|response|both)$")
    attribute_mappings: List[dict] = Field(default_factory=lambda: [dict(m) for m in DEFAULT_MAPPINGS])
    sp_cert: Optional[str] = Field(None, max_length=20000)
    require_signed_requests: bool = False
    default_relay_state: Optional[str] = Field(None, max_length=512)
    validity_seconds: int = Field(300, ge=60, le=3600)


class MetadataBody(BaseModel):
    xml: str = Field(..., max_length=P.MAX_MESSAGE_BYTES)


def _cert_checked(pem: Optional[str]) -> Optional[str]:
    if not pem or not pem.strip():
        return None
    from cryptography import x509
    from cryptography.hazmat.primitives.asymmetric import rsa

    try:
        c = x509.load_pem_x509_certificate(pem.strip().encode())
    except ValueError:
        raise HTTPException(status_code=422, detail="The certificate must be a PEM X.509 certificate")
    if not isinstance(c.public_key(), rsa.RSAPublicKey):
        raise HTTPException(status_code=422, detail="Only RSA certificates are supported")
    return pem.strip() + "\n"


def provider_dict(db: Session, p: SamlProvider) -> dict:
    cert = keys.active(db).cert_pem
    return {
        "sp_entity_id": p.sp_entity_id, "acs_url": p.acs_url, "audience": p.audience, "name_id_format": p.name_id_format, "name_id_attribute": p.name_id_attribute, "signing": p.signing,
        "attribute_mappings": p.attribute_mappings, "has_sp_cert": bool(p.sp_cert), "sp_cert": p.sp_cert,
        "require_signed_requests": p.require_signed_requests, "default_relay_state": p.default_relay_state, "validity_seconds": p.validity_seconds,
        "idp": {"entity_id": P.idp_entity_id(), "sso_url": P.sso_url(), "metadata_url": settings.OIDC_ISSUER.rstrip("/") + "/saml/metadata",
                "certificate_fingerprint_sha256": keys.fingerprint(cert), "certificate_pem": cert},
    }


def _app(db: Session, app_id: int) -> Application:
    a = db.get(Application, app_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return a


@admin_router.get("/{app_id}/saml")
def get_saml(app_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    _app(db, app_id)
    p = db.query(SamlProvider).filter(SamlProvider.application_id == app_id).first()
    out = {"configured": p is not None, "provider": provider_dict(db, p) if p else None,
           "idp": {"entity_id": P.idp_entity_id(), "sso_url": P.sso_url(), "metadata_url": settings.OIDC_ISSUER.rstrip("/") + "/saml/metadata"}}
    db.commit()
    return out


@admin_router.put("/{app_id}/saml")
def put_saml(app_id: int, body: SamlBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    a = _app(db, app_id)
    if a.sign_on_mode != "saml":
        raise HTTPException(status_code=409, detail="Set the sign-on method to SAML 2.0 first")
    try:
        acs = oidc_clients.validate_redirect_uri(body.acs_url, "ACS URL")
    except oidc_clients.ClientError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if (body.default_relay_state and len(body.default_relay_state.encode()) > 512):
        raise HTTPException(status_code=422, detail="Invalid NameID format or RelayState")
    cert = _cert_checked(body.sp_cert)
    if body.require_signed_requests and not cert:
        raise HTTPException(status_code=422, detail="Upload the SP's certificate to require signed requests")
    maps = _checked_mappings(body.attribute_mappings)
    nid_attr = None
    if body.name_id_format == "attribute":
        nid_attr = (body.name_id_attribute or "").strip()
        if not _ATTR_KEY.match(nid_attr):
            raise HTTPException(status_code=422, detail="Name ID attribute must look like attr:<profile key>")
    p = db.query(SamlProvider).filter(SamlProvider.application_id == a.id).first()
    new = p is None
    if new:
        p = SamlProvider(application_id=a.id)
        db.add(p)
    p.sp_entity_id, p.acs_url, p.audience = body.sp_entity_id.strip(), acs, (body.audience or "").strip() or None
    p.name_id_attribute = nid_attr
    p.name_id_format, p.signing, p.attribute_mappings, p.sp_cert = body.name_id_format, body.signing, maps, cert
    p.require_signed_requests, p.default_relay_state, p.validity_seconds = body.require_signed_requests, body.default_relay_state, body.validity_seconds
    p.updated_at = _now()
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Another application already uses that SP entity ID")
    record(db, AuditAction.APPLICATION_SAML_UPDATED, request, actor, a.id, "application",
           {"sp": p.sp_entity_id, "acs": p.acs_url, "name_id": p.name_id_format, "signing": p.signing, "signed_requests": p.require_signed_requests, "new": new})
    out = provider_dict(db, p)
    db.commit()
    return {"configured": True, "provider": out}


@admin_router.delete("/{app_id}/saml")
def delete_saml(app_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    a = _app(db, app_id)
    p = db.query(SamlProvider).filter(SamlProvider.application_id == a.id).first()
    if p is None:
        raise HTTPException(status_code=404, detail="No SAML configuration")
    db.delete(p)
    record(db, AuditAction.APPLICATION_SAML_REMOVED, request, actor, a.id, "application", {"sp": p.sp_entity_id})
    db.commit()
    return {"success": True}


PRESETS = [
    {"id": "basic", "label": "Basic (email, first name, last name)", "mappings": [dict(m, required=True) for m in DEFAULT_MAPPINGS]},
    {"id": "extended", "label": "Extended (adds username, display name, groups)", "mappings": [
        {"name": "email", "source": "email", "required": True}, {"name": "firstName", "source": "first_name", "required": True},
        {"name": "lastName", "source": "last_name", "required": True}, {"name": "username", "source": "username"},
        {"name": "displayName", "source": "display_name"}, {"name": "groups", "source": "groups"}]},
]


@admin_router.get("/saml/presets")
def presets(_: User = Depends(require_admin)):
    return {"items": PRESETS, "sources": sorted(SOURCES), "filters": list(FILTERS)}


@admin_router.get("/{app_id}/saml/preview")
def preview(app_id: int, user_id: int = Query(...), db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """What this application would receive for a user (unsigned, nothing is issued). Lets an administrator check a JIT mapping."""
    _app(db, app_id)
    p = db.query(SamlProvider).filter(SamlProvider.application_id == app_id).first()
    u = db.get(User, user_id)
    if p is None:
        raise HTTPException(status_code=404, detail="No SAML configuration")
    if u is None:
        raise HTTPException(status_code=404, detail="User not found")
    attrs, missing = resolve_attributes(u, p.attribute_mappings)
    nid = name_id_value(p, u)
    if not nid:
        missing.insert(0, "NameID")
    return {"name_id": nid, "name_id_format": NAME_ID_URN[p.name_id_format], "attributes": [{"name": n, "values": v} for n, v in attrs], "missing_required": missing,
            "would_issue": not missing}


@admin_router.post("/saml/import-metadata")
def import_metadata(body: MetadataBody, _: User = Depends(require_admin)):
    """Parse SP metadata pasted by the administrator (nothing is fetched from the network). Returns values to review, saves nothing."""
    try:
        return P.parse_sp_metadata(body.xml.encode())
    except P.SamlError as e:
        raise HTTPException(status_code=422, detail=str(e))


@admin_router.post("/saml/rotate-key")
def rotate_key(request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    if not actor.is_super_admin:
        raise HTTPException(status_code=403, detail="Only a super administrator can rotate the SAML signing certificate")
    k = keys.rotate(db)
    record(db, AuditAction.SAML_KEY_ROTATED, request, actor, k.id, "saml_signing_key", {"fingerprint": keys.fingerprint(k.cert_pem)})
    db.commit()
    return {"fingerprint": keys.fingerprint(k.cert_pem), "note": "Service providers must import the new certificate; the previous one stays in the metadata until removed."}
