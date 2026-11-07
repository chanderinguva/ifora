"""SCIM <-> IdentityForge attribute mapping (ADR 007 D3).

Reading from a payload goes through a fixed list of attributes: nothing outside it (is_admin, is_super_admin,
password, tenant_id, status other than via `active`) can reach the User model.
"""

import hashlib
import re
from typing import Any, Dict, List, Optional

from email_validator import EmailNotValidError, validate_email
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.profiles import catalog as profile_catalog
from backend.app.scim.errors import invalid_value
from backend.app.scim.patch import AttrDef, PatchSchema

USER_URN = "urn:ietf:params:scim:schemas:core:2.0:User"
GROUP_URN = "urn:ietf:params:scim:schemas:core:2.0:Group"
ENTERPRISE_URN = "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"
PROFILE_URN = "urn:identityforge:params:scim:schemas:extension:profile:2.0:User"
LIST_URN = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
PATCH_URN = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
SPC_URN = "urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"
RT_URN = "urn:ietf:params:scim:schemas:core:2.0:ResourceType"
SCHEMA_URN = "urn:ietf:params:scim:schemas:core:2.0:Schema"

# SCIM attribute -> profile catalog key
CORE_PROFILE = {"title": "title", "locale": "locale", "timezone": "timezone"}
ENTERPRISE_PROFILE = {"department": "department", "costCenter": "cost_center", "employeeNumber": "employee_id"}
MAPPED_KEYS = set(CORE_PROFILE.values()) | set(ENTERPRISE_PROFILE.values()) | {"phone", "manager"}
_USERNAME = re.compile(r"^[a-z0-9][a-z0-9._@+\-]{1,99}$")


def base_url() -> str:
    return settings.OIDC_ISSUER.rstrip("/") + "/scim/v2"


def etag(*parts: Any) -> str:
    return 'W/"' + hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:20] + '"'


# ---- schemas for the PATCH engine ---------------------------------------------------------

def user_patch_schema(db: Session) -> PatchSchema:
    contact = ("value", "type", "primary", "display")
    core = {
        "userName": AttrDef(), "externalId": AttrDef(), "active": AttrDef(), "displayName": AttrDef(),
        "title": AttrDef(), "locale": AttrDef(), "timezone": AttrDef(),
        "name": AttrDef(subs=("givenName", "familyName", "formatted")),
        "emails": AttrDef(subs=contact, multi=True),
        "phoneNumbers": AttrDef(subs=contact, multi=True),
        "groups": AttrDef(subs=("value", "display", "$ref"), multi=True, readonly=True),
    }
    enterprise = {k: AttrDef() for k in ENTERPRISE_PROFILE}
    enterprise["manager"] = AttrDef(subs=("value", "displayName"))
    extra = {a.key: AttrDef() for a in profile_catalog.catalog(db) if a.key not in MAPPED_KEYS}
    return PatchSchema(core, {ENTERPRISE_URN: enterprise, PROFILE_URN: extra}, core_urn=USER_URN)


def group_patch_schema() -> PatchSchema:
    core = {
        "displayName": AttrDef(), "externalId": AttrDef(),
        "members": AttrDef(subs=("value", "display", "$ref", "type"), multi=True),
    }
    return PatchSchema(core, core_urn=GROUP_URN)


# ---- render ---------------------------------------------------------------------------------

def render_user(db: Session, user, external_id: Optional[str]) -> Dict[str, Any]:
    attrs = user.get_profile_attributes()
    doc: Dict[str, Any] = {
        "schemas": [USER_URN],
        "id": user.public_id,
        "userName": user.username,
        "name": {"givenName": user.first_name, "familyName": user.last_name, "formatted": user.name},
        "displayName": user.name,
        "emails": [{"value": user.email, "type": "work", "primary": True}],
        "active": user.status == "active",
    }
    if external_id:
        doc["externalId"] = external_id
    for scim_key, key in CORE_PROFILE.items():
        if attrs.get(key) not in (None, ""):
            doc[scim_key] = attrs[key]
    if attrs.get("phone") not in (None, ""):
        doc["phoneNumbers"] = [{"value": str(attrs["phone"]), "type": "work", "primary": True}]
    ent = {sk: attrs[k] for sk, k in ENTERPRISE_PROFILE.items() if attrs.get(k) not in (None, "")}
    if attrs.get("manager") not in (None, ""):
        ent["manager"] = {"value": str(attrs["manager"])}
    if ent:
        doc[ENTERPRISE_URN] = ent
        doc["schemas"].append(ENTERPRISE_URN)
    catalog_keys = {a.key for a in profile_catalog.catalog(db)}
    extra = {k: v for k, v in attrs.items() if k in catalog_keys and k not in MAPPED_KEYS and v not in (None, "")}
    if extra:
        doc[PROFILE_URN] = extra
        doc["schemas"].append(PROFILE_URN)
    visible = [g for g in user.groups if not g.is_system_group]
    doc["groups"] = [
        {"value": g.public_id, "display": g.name, "$ref": f"{base_url()}/Groups/{g.public_id}"} for g in sorted(visible, key=lambda g: g.id)
    ]
    return doc


def user_meta(user, external_id: Optional[str]) -> Dict[str, Any]:
    return {
        "resourceType": "User",
        "created": user.created_at.isoformat() if user.created_at else None,
        "lastModified": user.updated_at.isoformat() if user.updated_at else None,
        "location": f"{base_url()}/Users/{user.public_id}",
        "version": etag("u", user.updated_at, external_id, user.status),
    }


# ---- ingest ----------------------------------------------------------------------------------

def _as_bool(v: Any, what: str) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str) and v.strip().lower() in ("true", "false"):  # Entra sends "True"/"False"
        return v.strip().lower() == "true"
    raise invalid_value(f"{what} must be true or false")


def _text(v: Any, what: str, max_len: int, *, required: bool = False) -> Optional[str]:
    if v is None or (isinstance(v, str) and not v.strip()):
        if required:
            raise invalid_value(f"{what} is required")
        return None
    if not isinstance(v, str):
        raise invalid_value(f"{what} must be a string")
    v = v.strip()
    if len(v) > max_len:
        raise invalid_value(f"{what} is limited to {max_len} characters")
    return v


def _pick(items: Any, what: str) -> Optional[str]:
    """Primary entry, else a 'work' one, else the first. Only a single value is stored."""
    if items is None:
        return None
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        raise invalid_value(f"{what} must be an array of objects")
    if not items:
        return None
    def ok(i):
        return isinstance(i.get("value"), str) and i["value"].strip()
    cands = [i for i in items if ok(i)]
    if not cands:
        return None
    for test in (lambda i: str(i.get("primary")).lower() == "true", lambda i: str(i.get("type", "")).lower() == "work"):
        for i in cands:
            if test(i):
                return i["value"].strip()
    return cands[0]["value"].strip()


def valid_email(value: str) -> Optional[str]:
    try:
        return validate_email(value, check_deliverability=False).normalized.lower()[:255]
    except EmailNotValidError:
        return None


def ingest_user(db: Session, doc: Any, *, current_attrs: Dict[str, Any], current_status: Optional[str]) -> Dict[str, Any]:
    """Validate a SCIM user document and return the values to store. Raises ScimError (400 invalidValue)."""
    if not isinstance(doc, dict):
        raise invalid_value("Body must be a JSON object")
    user_name = _text(doc.get("userName"), "userName", 100, required=True).lower()
    if not _USERNAME.match(user_name):
        raise invalid_value("userName must be 2-100 characters: letters, digits and . _ @ + -")
    email_raw = _pick(doc.get("emails"), "emails")
    if email_raw is None and "@" in user_name:
        email_raw = user_name
    if email_raw is None:
        raise invalid_value("An email address is required (emails or an email-shaped userName)")
    email = valid_email(email_raw)
    if email is None:
        raise invalid_value("Email address is not valid")
    name = doc.get("name")
    if not isinstance(name, dict):
        raise invalid_value("name.givenName and name.familyName are required")
    first = _text(name.get("givenName"), "name.givenName", 100, required=True)
    last = _text(name.get("familyName"), "name.familyName", 100, required=True)
    active: Optional[bool] = None
    if "active" in doc and doc["active"] is not None:
        active = _as_bool(doc["active"], "active")
    external_id = _text(doc.get("externalId"), "externalId", 255)

    desired: Dict[str, Any] = {a.key: None for a in profile_catalog.catalog(db)}
    for scim_key, key in CORE_PROFILE.items():
        if scim_key in doc:
            desired[key] = doc[scim_key]
    phone = _pick(doc.get("phoneNumbers"), "phoneNumbers")
    if "phoneNumbers" in doc:
        desired["phone"] = phone
    ent = doc.get(ENTERPRISE_URN)
    if ent is not None and not isinstance(ent, dict):
        raise invalid_value("Enterprise extension must be an object")
    for scim_key, key in ENTERPRISE_PROFILE.items():
        if ent and scim_key in ent:
            desired[key] = ent[scim_key]
    if ent and "manager" in ent:
        m = ent["manager"]
        desired["manager"] = m.get("value") if isinstance(m, dict) else m
    ext = doc.get(PROFILE_URN)
    if ext is not None and not isinstance(ext, dict):
        raise invalid_value("Profile extension must be an object")
    for k, v in (ext or {}).items():
        if k in MAPPED_KEYS:
            continue
        desired[k] = v
    for k, v in list(desired.items()):
        if isinstance(v, (dict, list)):
            raise invalid_value(f"Attribute '{k}' must be a simple value")
    try:
        cleaned = profile_catalog.validate_values(db, desired, only_editable_by_user=False, current=current_attrs)
    except profile_catalog.PermissionError_ as e:
        raise invalid_value(e.message)
    except profile_catalog.AttributeError_ as e:
        raise invalid_value(str(e))
    catalog_keys = {a.key for a in profile_catalog.catalog(db)}
    attrs = {k: v for k, v in current_attrs.items() if k not in catalog_keys}  # legacy values SCIM cannot see
    attrs.update({k: v for k, v in cleaned.items() if v is not None})
    return {
        "username": user_name, "email": email, "first_name": first, "last_name": last,
        "active": active, "external_id": external_id, "profile": attrs,
    }


def render_group(group, members: List[Any], external_id: Optional[str]) -> Dict[str, Any]:
    doc: Dict[str, Any] = {
        "schemas": [GROUP_URN],
        "id": group.public_id,
        "displayName": group.name,
        "members": [
            {"value": u.public_id, "display": f"{u.first_name} {u.last_name}", "type": "User",
             "$ref": f"{base_url()}/Users/{u.public_id}"}
            for u in members
        ],
    }
    if external_id:
        doc["externalId"] = external_id
    return doc


def group_meta(group, member_ids: List[int], external_id: Optional[str]) -> Dict[str, Any]:
    return {
        "resourceType": "Group",
        "created": group.created_at.isoformat() if group.created_at else None,
        "lastModified": group.updated_at.isoformat() if group.updated_at else None,
        "location": f"{base_url()}/Groups/{group.public_id}",
        "version": etag("g", group.updated_at, group.name, external_id, sorted(member_ids)),
    }
