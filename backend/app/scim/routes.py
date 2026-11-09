"""SCIM 2.0 resource endpoints (ADR 007). Mounted at /scim/v2 by app.py; every route needs a valid bearer token."""

import json
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import String, cast, delete, exists, func, insert, literal, select, true, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from backend.app.audit.model import AuditAction
from backend.app.auth.sessions_util import revoke_user_sessions
from backend.app.users import lifecycle
from backend.app.groups import rules as group_rules
from backend.app.groups.model import Group, user_group_association as assoc
from backend.app.oidc.models import RefreshToken
from backend.app.profiles import catalog as profile_catalog
from backend.app.config import settings
from backend.app.scim import discovery, filter as flt, mapping, projection, retention
from backend.app.scim.auth import Ctx, audit, get_ctx
from backend.app.scim.errors import (
    MEDIA_TYPE, ScimError, invalid_syntax, invalid_value, mutability, not_found, uniqueness,
)
from backend.app.scim.models import ScimLink
from backend.app.scim.patch import apply_patch
from backend.app.users.model import User

router = APIRouter()

MAX_BODY = 1024 * 1024
MAX_COUNT = discovery.MAX_RESULTS
DEFAULT_COUNT = 100
MAX_MEMBERS = 5000
MAX_START = 1_000_000


class ScimResponse(JSONResponse):
    media_type = MEDIA_TYPE


def respond(doc: Any, status: int = 200, etag: Optional[str] = None, location: Optional[str] = None) -> ScimResponse:
    headers = {"Cache-Control": "no-store"}
    if etag:
        headers["ETag"] = etag
    if location:
        headers["Location"] = location
    return ScimResponse(doc, status_code=status, headers=headers)


async def read_json(request: Request, _auth: Ctx = Depends(get_ctx)) -> Any:
    # depends on get_ctx so authentication always happens before the body is read
    ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if ctype not in ("application/json", "application/scim+json"):
        raise ScimError(415, "Content-Type must be application/scim+json or application/json")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY:
        raise ScimError(413, "Request body is too large")
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > MAX_BODY:
            raise ScimError(413, "Request body is too large")
    try:
        return json.loads(bytes(buf).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise invalid_syntax("Body is not valid JSON")


# ---- helpers ------------------------------------------------------------------------------------

def _int_param(v: Optional[str], name: str, default: int) -> int:
    if v is None or v == "":
        return default
    try:
        return int(v)
    except ValueError:
        raise invalid_value(f"{name} must be an integer")


def page_params(start: Optional[str], count: Optional[str]) -> tuple:
    s = min(max(_int_param(start, "startIndex", 1), 1), MAX_START)
    c = min(max(_int_param(count, "count", DEFAULT_COUNT), 0), MAX_COUNT)
    return s, c


def check_if_match(request: Request, current: str) -> None:
    h = request.headers.get("if-match")
    if h is None or h.strip() == "*":
        return
    wanted = {x.strip() for x in h.split(",")}
    if current not in wanted:
        raise ScimError(412, "The resource has changed (ETag mismatch)")


def list_response(resources: List[dict], total: int, start: int) -> dict:
    return {"schemas": [mapping.LIST_URN], "totalResults": total, "startIndex": start,
            "itemsPerPage": len(resources), "Resources": resources}


def _ext_ids(db: Session, kind: str, ids: List[int]) -> Dict[int, str]:
    if not ids:
        return {}
    col = ScimLink.user_id if kind == "user" else ScimLink.group_id
    return {r[0]: r[1] for r in db.query(col, ScimLink.external_id).filter(col.in_(ids)).all()}


def _set_external_id(db: Session, kind: str, rid: int, external_id: Optional[str]) -> None:
    col = ScimLink.user_id if kind == "user" else ScimLink.group_id
    link = db.query(ScimLink).filter(col == rid).first()
    if external_id is None:
        if link is not None:
            db.delete(link)
        return
    if link is None:
        db.add(ScimLink(external_id=external_id, **({"user_id": rid} if kind == "user" else {"group_id": rid})))
    else:
        link.external_id = external_id


def _external_taken(db: Session, kind: str, external_id: Optional[str], exclude_id: Optional[int]) -> bool:
    if external_id is None:
        return False
    col = ScimLink.user_id if kind == "user" else ScimLink.group_id
    q = db.query(ScimLink.id).filter(col.is_not(None), ScimLink.external_id == external_id)
    if exclude_id is not None:
        q = q.filter(col != exclude_id)
    return q.first() is not None


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise uniqueness("A resource with these unique values already exists")


# ---- discovery ----------------------------------------------------------------------------------

@router.get("/ServiceProviderConfig")
def get_spc(ctx: Ctx = Depends(get_ctx)):
    return respond(discovery.service_provider_config())


@router.get("/ResourceTypes")
def get_resource_types(ctx: Ctx = Depends(get_ctx)):
    items = discovery.resource_types()
    return respond(list_response(items, len(items), 1))


@router.get("/ResourceTypes/{rid}")
def get_resource_type(rid: str, ctx: Ctx = Depends(get_ctx)):
    for r in discovery.resource_types():
        if r["id"].lower() == rid.lower():
            return respond(r)
    raise not_found()


@router.get("/Schemas")
def get_schemas(ctx: Ctx = Depends(get_ctx)):
    items = discovery.schemas()
    return respond(list_response(items, len(items), 1))


@router.get("/Schemas/{sid}")
def get_schema(sid: str, ctx: Ctx = Depends(get_ctx)):
    for s in discovery.schemas():
        if s["id"] == sid:
            return respond(s)
    raise not_found()


@router.post("/Bulk")
def bulk_endpoint(body: Any = Depends(read_json), ctx: Ctx = Depends(get_ctx)):
    from backend.app.scim import bulk as bulk_mod

    table = {
        ("POST", "users", False): lambda c, r, i, d: create_user(r, d, c),
        ("PUT", "users", True): lambda c, r, i, d: replace_user(i, r, d, c),
        ("PATCH", "users", True): lambda c, r, i, d: patch_user(i, r, d, c),
        ("DELETE", "users", True): lambda c, r, i, d: delete_user(i, r, c),
        ("POST", "groups", False): lambda c, r, i, d: create_group(d, c),
        ("PUT", "groups", True): lambda c, r, i, d: replace_group(i, r, d, c),
        ("PATCH", "groups", True): lambda c, r, i, d: patch_group(i, r, d, c),
        ("DELETE", "groups", True): lambda c, r, i, d: delete_group(i, r, c),
    }
    return respond(bulk_mod.execute(ctx, body, table, MAX_BODY))


@router.api_route("/Bulk", methods=["GET", "PUT", "PATCH", "DELETE"])
def bulk_method_not_allowed(ctx: Ctx = Depends(get_ctx)):
    raise ScimError(405, "Bulk accepts POST only")


@router.api_route("/Me", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def me(ctx: Ctx = Depends(get_ctx)):
    raise ScimError(501, "The /Me endpoint is not supported")


@router.api_route("/.search", methods=["POST"])
def search_root(ctx: Ctx = Depends(get_ctx)):
    raise ScimError(501, "Cross-resource search is not supported; POST to /Users/.search or /Groups/.search")


SEARCH_URN = "urn:ietf:params:scim:api:messages:2.0:SearchRequest"


def _search_params(body: Any) -> dict:
    if not isinstance(body, dict) or SEARCH_URN not in (body.get("schemas") or []):
        raise invalid_syntax("Body must be a SearchRequest")
    out = {}
    for k in ("filter", "sortBy", "sortOrder", "attributes", "excludedAttributes"):
        v = body.get(k)
        if v is not None and not isinstance(v, (str, list)):
            raise invalid_syntax(f"{k} must be a string")
        out[k] = ",".join(v) if isinstance(v, list) and k in ("attributes", "excludedAttributes") else v
    for k in ("startIndex", "count"):
        v = body.get(k)
        if v is not None and (isinstance(v, bool) or not isinstance(v, int)):
            raise invalid_syntax(f"{k} must be an integer")
        out[k] = None if v is None else str(v)
    return out


def _search(kind: str, body: Any, ctx: Ctx):
    p = _search_params(body)
    fn = _users_page if kind == "users" else _groups_page
    doc = fn(ctx, p["filter"], p["startIndex"], p["count"], p["sortBy"], p["sortOrder"])
    attrs, excl = projection.parse(p["attributes"]), projection.parse(p["excludedAttributes"])
    if attrs or excl:
        doc = projection.apply(doc, attrs, excl)
    return respond(doc)


@router.post("/Users/.search")
def search_users(body: Any = Depends(read_json), ctx: Ctx = Depends(get_ctx)):
    return _search("users", body, ctx)


@router.post("/Groups/.search")
def search_groups(body: Any = Depends(read_json), ctx: Ctx = Depends(get_ctx)):
    return _search("groups", body, ctx)


def _order(attrs: dict, sort_by: Optional[str], sort_order: Optional[str], tiebreak):
    """ORDER BY for sortBy/sortOrder. Strings sort case-insensitively; missing values last; id breaks ties."""
    if sort_order is not None and sort_order.lower() not in ("ascending", "descending"):
        raise invalid_value("sortOrder must be ascending or descending")
    if not sort_by:
        return [tiebreak]
    attr = attrs.get(sort_by.strip().lower())
    if attr is None or attr.expr is None or attr.kind not in ("str", "date", "bool") or sort_by.strip().lower().startswith(("emails.t", "emails.p")):
        raise invalid_value(f"Cannot sort by '{sort_by[:60]}'")
    col = func.lower(attr.expr) if attr.kind == "str" else attr.expr
    desc_ = (sort_order or "ascending").lower() == "descending"
    return [(col.desc() if desc_ else col.asc()).nulls_last(), tiebreak]


# ---- users --------------------------------------------------------------------------------------

_ext_user = select(ScimLink.external_id).where(ScimLink.user_id == User.id).correlate(User).scalar_subquery()
USER_FILTER_ATTRS = {
    "id": flt.Attr("str", User.public_id),
    "username": flt.Attr("str", User.username),
    "externalid": flt.Attr("str", _ext_user),
    "active": flt.Attr("bool", User.status == "active"),
    "displayname": flt.Attr("str", func.concat(User.first_name, " ", User.last_name)),
    "name.givenname": flt.Attr("str", User.first_name),
    "name.familyname": flt.Attr("str", User.last_name),
    "emails.value": flt.Attr("str", User.email),
    "emails": flt.Attr("str", User.email),
    "emails.type": flt.Attr("str", literal("work")),      # we store one email and always render it as the primary work address
    "emails.primary": flt.Attr("bool", true()),
    "meta.lastmodified": flt.Attr("date", User.updated_at),
    "meta.created": flt.Attr("date", User.created_at),
}


def render_user_resource(db: Session, user: User, external_id: Optional[str]) -> tuple:
    doc = mapping.render_user(db, user, external_id)
    doc["meta"] = mapping.user_meta(user, external_id)
    return doc, doc["meta"]["version"]


def _get_user(db: Session, uid: str) -> User:
    user = db.query(User).filter(User.public_id == uid[:36]).first() if len(uid) <= 36 else None
    if user is None:
        raise not_found("User not found")
    return user


def _guard_admin(user: User) -> None:
    if user.is_admin or user.is_super_admin:
        raise ScimError(403, "Administrator accounts cannot be changed through SCIM")


def _unique_user(db: Session, data: dict, exclude_id: Optional[int]) -> None:
    def taken(col, val):
        q = db.query(User.id).filter(func.lower(col) == val.lower())
        return (q.filter(User.id != exclude_id) if exclude_id is not None else q).first() is not None

    if taken(User.username, data["username"]):
        raise uniqueness("userName is already in use")
    if taken(User.email, data["email"]):
        raise uniqueness("Email address is already in use")
    if _external_taken(db, "user", data["external_id"], exclude_id):
        raise uniqueness("externalId is already in use")


def _deactivate_side_effects(db: Session, user: User) -> None:
    revoke_user_sessions(db, user.id)
    db.execute(update(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
               .values(revoked_at=datetime.now(timezone.utc)))


def _users_page(ctx: Ctx, filter, startIndex, count, sortBy=None, sortOrder=None) -> dict:
    db = ctx.db
    start, cnt = page_params(startIndex, count)
    q = db.query(User)
    if filter is not None:
        q = q.filter(flt.build(filter, USER_FILTER_ATTRS))
    order = _order(USER_FILTER_ATTRS, sortBy, sortOrder, User.id)
    total = q.count()
    users = (q.options(selectinload(User.groups)).order_by(*order).offset(start - 1).limit(cnt).all()) if cnt else []
    ext = _ext_ids(db, "user", [u.id for u in users])
    return list_response([render_user_resource(db, u, ext.get(u.id))[0] for u in users], total, start)


@router.get("/Users")
def list_users(request: Request, filter: Optional[str] = None, startIndex: Optional[str] = None,
               count: Optional[str] = None, sortBy: Optional[str] = None, sortOrder: Optional[str] = None,
               ctx: Ctx = Depends(get_ctx)):
    return respond(_users_page(ctx, filter, startIndex, count, sortBy, sortOrder))


@router.get("/Users/{uid}")
def get_user(uid: str, ctx: Ctx = Depends(get_ctx)):
    user = _get_user(ctx.db, uid)
    doc, tag = render_user_resource(ctx.db, user, _ext_ids(ctx.db, "user", [user.id]).get(user.id))
    return respond(doc, etag=tag)


@router.post("/Users")
def create_user(request: Request, body: Any = Depends(read_json), ctx: Ctx = Depends(get_ctx)):
    db = ctx.db
    data = mapping.ingest_user(db, body, current_attrs={}, current_status=None)
    _unique_user(db, data, None)
    user = User(
        email=data["email"], username=data["username"], first_name=data["first_name"], last_name=data["last_name"],
        password=secrets.token_urlsafe(24),  # unknown to everyone; the password attribute is never read (ADR 007 D5)
    )
    user.status = "deprovisioned" if data["active"] is False else "active"
    user.set_profile_attributes(data["profile"])
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise uniqueness("A user with this userName or email already exists")
    _set_external_id(db, "user", user.id, data["external_id"])
    audit(db, AuditAction.SCIM_USER_CREATED, ctx.request, ctx.token, user.id, "user",
          {"active": user.status == "active", "has_external_id": data["external_id"] is not None})
    db.flush()
    group_rules.evaluate_user(db, user, ctx.request, None)
    _commit(db)
    db.refresh(user)
    doc, tag = render_user_resource(db, user, data["external_id"])
    return respond(doc, 201, etag=tag, location=doc["meta"]["location"])


def apply_user_update(ctx: Ctx, user: User, data: dict) -> None:
    db = ctx.db
    _guard_admin(user)
    _unique_user(db, data, user.id)
    changed: List[str] = []
    for attr, key in (("username", "userName"), ("email", "email"), ("first_name", "name.givenName"), ("last_name", "name.familyName")):
        if getattr(user, attr) != data[attr]:
            setattr(user, attr, data[attr])
            changed.append(key)
    if user.get_profile_attributes() != data["profile"]:
        before = user.get_profile_attributes()
        user.set_profile_attributes(data["profile"])
        changed += sorted(k for k in set(before) | set(data["profile"]) if before.get(k) != data["profile"].get(k))
    old_ext = _ext_ids(db, "user", [user.id]).get(user.id)
    if old_ext != data["external_id"]:
        _set_external_id(db, "user", user.id, data["external_id"])
        changed.append("externalId")
    action = AuditAction.SCIM_USER_UPDATED
    if data["active"] is True and user.status != "active":
        lifecycle.set_status(db, user, "active", ctx.request, None, audit=False)
        changed.append("active")
        action = AuditAction.SCIM_USER_ACTIVATED
        retention.clear_deactivation(db, user)
    elif data["active"] is False and user.status != "deprovisioned":
        lifecycle.set_status(db, user, "deprovisioned", ctx.request, None, audit=False)  # also leaves every group
        changed.append("active")
        action = AuditAction.SCIM_USER_DEACTIVATED
        _deactivate_side_effects(db, user)
    if changed:
        user.updated_at = datetime.now(timezone.utc)
        db.flush()
        group_rules.evaluate_user(db, user, ctx.request, None)
        db.flush()
        if user.status == "deprovisioned" and action == AuditAction.SCIM_USER_DEACTIVATED:
            retention.mark_deactivated(db, user, ctx.token)
        audit(db, action, ctx.request, ctx.token, user.id, "user", {"changed": changed})
    _commit(db)
    db.refresh(user)


@router.put("/Users/{uid}")
def replace_user(uid: str, request: Request, body: Any = Depends(read_json), ctx: Ctx = Depends(get_ctx)):
    db = ctx.db
    user = _get_user(db, uid)
    _guard_admin(user)
    cur_ext = _ext_ids(db, "user", [user.id]).get(user.id)
    check_if_match(request, mapping.user_meta(user, cur_ext)["version"])
    data = mapping.ingest_user(db, body, current_attrs=user.get_profile_attributes(), current_status=user.status)
    apply_user_update(ctx, user, data)
    doc, tag = render_user_resource(db, user, data["external_id"])
    return respond(doc, etag=tag)


@router.patch("/Users/{uid}")
def patch_user(uid: str, request: Request, body: Any = Depends(read_json), ctx: Ctx = Depends(get_ctx)):
    db = ctx.db
    user = _get_user(db, uid)
    _guard_admin(user)
    if not isinstance(body, dict):
        raise invalid_syntax("Body must be a JSON object")
    cur_ext = _ext_ids(db, "user", [user.id]).get(user.id)
    check_if_match(request, mapping.user_meta(user, cur_ext)["version"])
    doc = mapping.render_user(db, user, cur_ext)
    ops = body.get("Operations", body.get("operations"))
    apply_patch(mapping.user_patch_schema(db), doc, ops)
    data = mapping.ingest_user(db, doc, current_attrs=user.get_profile_attributes(), current_status=user.status)
    apply_user_update(ctx, user, data)
    out, tag = render_user_resource(db, user, data["external_id"])
    return respond(out, etag=tag)


@router.delete("/Users/{uid}")
def delete_user(uid: str, request: Request, ctx: Ctx = Depends(get_ctx)):
    """Deprovision = deactivate. The row, its audit trail and memberships stay (ADR 007 D6)."""
    db = ctx.db
    user = _get_user(db, uid)
    _guard_admin(user)
    cur_ext = _ext_ids(db, "user", [user.id]).get(user.id)
    check_if_match(request, mapping.user_meta(user, cur_ext)["version"])
    if user.status != "deprovisioned":
        lifecycle.set_status(db, user, "deprovisioned", request, None, audit=False)
        user.updated_at = datetime.now(timezone.utc)
        _deactivate_side_effects(db, user)
        db.flush()
        group_rules.evaluate_user(db, user, request, None)
        db.flush()
        retention.mark_deactivated(db, user, ctx.token)
        audit(db, AuditAction.SCIM_USER_DEACTIVATED, request, ctx.token, user.id, "user", {"via": "delete"})
        _commit(db)
    return Response(status_code=204)


# ---- groups -------------------------------------------------------------------------------------

def _group_members_exists(pred):
    return exists(select(1).where(assoc.c.group_id == Group.id, assoc.c.user_id == User.id, pred(User.public_id)))


_ext_group = select(ScimLink.external_id).where(ScimLink.group_id == Group.id).correlate(Group).scalar_subquery()
GROUP_FILTER_ATTRS = {
    "id": flt.Attr("str", Group.public_id),
    "displayname": flt.Attr("str", Group.name),
    "externalid": flt.Attr("str", _ext_group),
    "members.value": flt.Attr("str", None, exists=_group_members_exists),
    "meta.lastmodified": flt.Attr("date", Group.updated_at),
    "meta.created": flt.Attr("date", Group.created_at),
}


def _get_group(db: Session, gid: str) -> Group:
    g = None
    if len(gid) <= 36 and not gid.isdigit():
        g = db.query(Group).filter(Group.public_id == gid).first()
    elif gid.isdigit() and len(gid) < 10 and settings.SCIM_ACCEPT_LEGACY_GROUP_IDS:
        # integer ids were what earlier versions handed out; IdPs that stored them keep working until switched off
        g = db.query(Group).filter(Group.id == int(gid)).first()
    if g is None or g.is_system_group:
        raise not_found("Group not found")
    return g


def _member_rows(db: Session, g: Group) -> List[tuple]:
    return db.execute(
        select(User, assoc.c.rule_id).join(assoc, assoc.c.user_id == User.id)
        .where(assoc.c.group_id == g.id).order_by(User.id)
    ).all()


def render_group_resource(db: Session, g: Group, external_id: Optional[str]) -> tuple:
    rows = _member_rows(db, g)
    doc = mapping.render_group(g, [r[0] for r in rows], external_id)
    doc["meta"] = mapping.group_meta(g, [r[0].id for r in rows], external_id)
    return doc, doc["meta"]["version"]


def ingest_group(doc: Any) -> dict:
    if not isinstance(doc, dict):
        raise invalid_value("Body must be a JSON object")
    name = doc.get("displayName")
    if not isinstance(name, str) or not name.strip():
        raise invalid_value("displayName is required")
    name = name.strip()
    if len(name) > 100:
        raise invalid_value("displayName is limited to 100 characters")
    ext = doc.get("externalId")
    if ext is not None and (not isinstance(ext, str) or len(ext) > 255):
        raise invalid_value("externalId must be a string of up to 255 characters")
    members = doc.get("members") or []
    if not isinstance(members, list):
        raise invalid_value("members must be an array")
    if len(members) > MAX_MEMBERS:
        raise ScimError(413, f"At most {MAX_MEMBERS} members per request", "tooMany")
    ids: List[str] = []
    for m in members:
        v = m.get("value") if isinstance(m, dict) else None
        if not isinstance(v, str) or not v or len(v) > 36:
            raise invalid_value("Each member needs a string 'value' (the user id)")
        if v not in ids:
            ids.append(v)
    return {"name": name, "external_id": ext or None, "members": ids}


def _name_taken(db: Session, name: str, exclude_id: Optional[int]) -> bool:
    q = db.query(Group.id).filter(func.lower(Group.name) == name.lower())
    if exclude_id is not None:
        q = q.filter(Group.id != exclude_id)
    return q.first() is not None


def _sync_members(ctx: Ctx, g: Group, public_ids: List[str]) -> Dict[str, int]:
    """Make the membership equal to `public_ids`. Rule-created memberships cannot be removed (409, nothing applied)."""
    db = ctx.db
    users = db.query(User).filter(User.public_id.in_(public_ids)).all() if public_ids else []
    if len(users) != len(public_ids):
        raise invalid_value("A member refers to an unknown user")
    from backend.app.admin_roles.resolve import group_has_roles

    desired = {u.id for u in users}
    current = {r[0].id: r[1] for r in _member_rows(db, g)}
    if group_has_roles(db, g.id) and desired != set(current):
        raise mutability("This group carries administrator roles; its membership cannot be changed through SCIM", 403)
    gone = [uid for uid in current if uid not in desired]
    if any(current[uid] is not None for uid in gone):
        raise mutability("A membership is managed by a group rule and cannot be removed through SCIM", 409)
    added = [uid for uid in desired if uid not in current]
    now = datetime.now(timezone.utc)
    for uid in added:
        db.execute(insert(assoc).values(user_id=uid, group_id=g.id, added_by_user_id=None, rule_id=None, added_at=now))
        audit(db, AuditAction.SCIM_GROUP_MEMBER_ADDED, ctx.request, ctx.token, g.id, "group", {"user_id": uid})
    if gone:
        db.execute(delete(assoc).where(assoc.c.group_id == g.id, assoc.c.user_id.in_(gone), assoc.c.rule_id.is_(None)))
        for uid in gone:
            audit(db, AuditAction.SCIM_GROUP_MEMBER_REMOVED, ctx.request, ctx.token, g.id, "group", {"user_id": uid})
    if added or gone:
        group_rules._recount(db, g.id)
        g.updated_at = now
    return {"added": len(added), "removed": len(gone)}


def _groups_page(ctx: Ctx, filter, startIndex, count, sortBy=None, sortOrder=None) -> dict:
    db = ctx.db
    start, cnt = page_params(startIndex, count)
    q = db.query(Group).filter(Group.is_system_group.is_(False))
    if filter is not None:
        q = q.filter(flt.build(filter, GROUP_FILTER_ATTRS))
    order = _order(GROUP_FILTER_ATTRS, sortBy, sortOrder, Group.id)
    total = q.count()
    groups = q.order_by(*order).offset(start - 1).limit(cnt).all() if cnt else []
    ext = _ext_ids(db, "group", [g.id for g in groups])
    return list_response([render_group_resource(db, g, ext.get(g.id))[0] for g in groups], total, start)


@router.get("/Groups")
def list_groups(filter: Optional[str] = None, startIndex: Optional[str] = None, count: Optional[str] = None,
                sortBy: Optional[str] = None, sortOrder: Optional[str] = None, ctx: Ctx = Depends(get_ctx)):
    return respond(_groups_page(ctx, filter, startIndex, count, sortBy, sortOrder))


@router.get("/Groups/{gid}")
def get_group(gid: str, ctx: Ctx = Depends(get_ctx)):
    g = _get_group(ctx.db, gid)
    doc, tag = render_group_resource(ctx.db, g, _ext_ids(ctx.db, "group", [g.id]).get(g.id))
    return respond(doc, etag=tag)


@router.post("/Groups")
def create_group(body: Any = Depends(read_json), ctx: Ctx = Depends(get_ctx)):
    db = ctx.db
    data = ingest_group(body)
    if _name_taken(db, data["name"], None):
        raise uniqueness("displayName is already in use")
    if _external_taken(db, "group", data["external_id"], None):
        raise uniqueness("externalId is already in use")
    g = Group(name=data["name"])
    db.add(g)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise uniqueness("A group with this displayName already exists")
    _set_external_id(db, "group", g.id, data["external_id"])
    audit(db, AuditAction.SCIM_GROUP_CREATED, ctx.request, ctx.token, g.id, "group", {"name": g.name})
    _sync_members(ctx, g, data["members"])
    _commit(db)
    db.refresh(g)
    doc, tag = render_group_resource(db, g, data["external_id"])
    return respond(doc, 201, etag=tag, location=doc["meta"]["location"])


def _apply_group(ctx: Ctx, g: Group, data: dict) -> None:
    db = ctx.db
    if _name_taken(db, data["name"], g.id):
        raise uniqueness("displayName is already in use")
    if _external_taken(db, "group", data["external_id"], g.id):
        raise uniqueness("externalId is already in use")
    changed = []
    if g.name != data["name"]:
        g.name = data["name"]
        changed.append("displayName")
    old_ext = _ext_ids(db, "group", [g.id]).get(g.id)
    if old_ext != data["external_id"]:
        _set_external_id(db, "group", g.id, data["external_id"])
        changed.append("externalId")
    if changed:
        g.updated_at = datetime.now(timezone.utc)
        audit(db, AuditAction.SCIM_GROUP_UPDATED, ctx.request, ctx.token, g.id, "group", {"changed": changed})
    _sync_members(ctx, g, data["members"])
    _commit(db)
    db.refresh(g)


@router.put("/Groups/{gid}")
def replace_group(gid: str, request: Request, body: Any = Depends(read_json), ctx: Ctx = Depends(get_ctx)):
    db = ctx.db
    g = _get_group(db, gid)
    _, tag = render_group_resource(db, g, _ext_ids(db, "group", [g.id]).get(g.id))
    check_if_match(request, tag)
    data = ingest_group(body)
    _apply_group(ctx, g, data)
    doc, tag = render_group_resource(db, g, data["external_id"])
    return respond(doc, etag=tag)


@router.patch("/Groups/{gid}")
def patch_group(gid: str, request: Request, body: Any = Depends(read_json), ctx: Ctx = Depends(get_ctx)):
    db = ctx.db
    g = _get_group(db, gid)
    if not isinstance(body, dict):
        raise invalid_syntax("Body must be a JSON object")
    ext = _ext_ids(db, "group", [g.id]).get(g.id)
    doc, tag = render_group_resource(db, g, ext)
    check_if_match(request, tag)
    apply_patch(mapping.group_patch_schema(), doc, body.get("Operations", body.get("operations")))
    data = ingest_group(doc)
    _apply_group(ctx, g, data)
    out, tag = render_group_resource(db, g, data["external_id"])
    return respond(out, etag=tag)


@router.delete("/Groups/{gid}")
def delete_group(gid: str, request: Request, ctx: Ctx = Depends(get_ctx)):
    db = ctx.db
    g = _get_group(db, gid)
    _, tag = render_group_resource(db, g, _ext_ids(db, "group", [g.id]).get(g.id))
    check_if_match(request, tag)
    if db.execute(select(group_rules.rule_targets.c.rule_id).where(group_rules.rule_targets.c.group_id == g.id)).first():
        raise mutability("This group is the target of a group rule and cannot be deleted through SCIM", 409)
    name, gid_int = g.name, g.id
    db.delete(g)
    audit(db, AuditAction.SCIM_GROUP_DELETED, request, ctx.token, gid_int, "group", {"name": name})
    _commit(db)
    return Response(status_code=204)
