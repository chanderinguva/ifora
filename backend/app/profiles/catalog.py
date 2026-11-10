"""User profile schema ("Profile editor", like Okta Universal Directory).

Every profile attribute a user can carry is declared here: its type, whether the user may edit it themselves,
and what it is for. This replaces the hard-coded self-editable list.

Security link with group rules (ADR 006): an attribute that users can edit themselves can never be used in a
group rule, and an attribute used by a rule cannot be made user-editable.
"""

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import Boolean, Column, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.db import Base
from backend.app.profiles.schemas import MAX_STR, valid_locale, valid_timezone
from backend.app.tenancy import TenantOwned

DATA_TYPES = ("string", "number", "boolean", "enum", "timezone", "locale")
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,49}$")
RESERVED = {
    "id", "email", "username", "first_name", "last_name", "password", "status", "is_admin", "is_super_admin",
    "groups", "tenant_id", "created_at", "updated_at",
}
MAX_ATTRIBUTES = 80

USER_TYPES = ["Employee", "Contingent Worker", "Intern", "Service Account", "Test Account", "Shared Account", "Agent Account"]
DEFAULT_USER_TYPE = USER_TYPES[0]

# key, display name, type, user editable, description
DEFAULTS = [
    # The Okta base user profile (keys are snake_case of Okta's names; login/email/firstName/lastName are core fields).
    ("middle_name", "Middle name", "string", True, "Okta middleName"),
    ("honorific_prefix", "Honorific prefix", "string", True, "Okta honorificPrefix, e.g. Dr."),
    ("honorific_suffix", "Honorific suffix", "string", True, "Okta honorificSuffix, e.g. Jr."),
    ("display_name", "Display name", "string", True, "Okta displayName"),
    ("nick_name", "Nickname", "string", True, "Okta nickName"),
    ("second_email", "Secondary email", "string", True, "Okta secondEmail"),
    ("profile_url", "Profile URL", "string", True, "Okta profileUrl"),
    ("primary_phone", "Primary phone", "string", True, "Okta primaryPhone"),
    ("mobile_phone", "Mobile phone", "string", True, "Okta mobilePhone"),
    ("street_address", "Street address", "string", True, "Okta streetAddress"),
    ("city", "City", "string", True, "Okta city"),
    ("state", "State", "string", True, "Okta state"),
    ("zip_code", "Zip or postal code", "string", True, "Okta zipCode"),
    ("country_code", "Country code", "string", True, "Okta countryCode, ISO 3166-1 alpha-2"),
    ("postal_address", "Mailing address", "string", True, "Okta postalAddress"),
    ("preferred_language", "Preferred language", "locale", True, "Okta preferredLanguage"),
    ("locale", "Locale", "locale", True, "Okta locale; date and number formats"),
    ("timezone", "Time zone", "timezone", True, "Okta timezone; used to display dates and times"),
    ("title", "Title", "string", True, "Okta title"),
    ("user_type", "User type", "enum", False, "Okta userType: what kind of account this is (a fixed list)"),
    ("employee_number", "Employee number", "string", False, "Okta employeeNumber"),
    ("cost_center", "Cost center", "string", False, "Okta costCenter"),
    ("organization", "Organization", "string", False, "Okta organization"),
    ("division", "Division", "string", False, "Okta division"),
    ("department", "Department", "string", False, "Okta department"),
    ("manager_id", "Manager ID", "string", False, "Okta managerId"),
    ("manager", "Manager", "string", False, "Okta manager"),
]


class ProfileAttribute(TenantOwned, Base):
    __tablename__ = "profile_attributes"
    __table_args__ = (UniqueConstraint("tenant_id", "key", name="uq_profile_attributes_tenant_key"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(50), nullable=False)
    display_name = Column(String(100), nullable=False)
    description = Column(String(500), nullable=True)
    data_type = Column(String(16), nullable=False)
    enum_options = Column(JSONB, nullable=True)
    user_editable = Column(Boolean, nullable=False, default=False)
    built_in = Column(Boolean, nullable=False, default=False, server_default="false")
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "display_name": self.display_name,
            "description": self.description,
            "data_type": self.data_type,
            "enum_options": self.enum_options,
            "user_editable": self.user_editable,
            "built_in": self.built_in,
        }


def ensure_defaults(db: Session) -> None:
    """Seed the built-in attributes, and top up any built-in a tenant is missing (new tenant, truncated test DB,
    or a release that added attributes). Built-ins cannot be deleted, so this never resurrects a removal."""
    have = {k for (k,) in db.query(ProfileAttribute.key).all()}
    missing = [(i, d) for i, d in enumerate(DEFAULTS) if d[0] not in have]
    if not missing:
        return
    for i, (key, name, typ, editable, desc) in missing:
        db.add(ProfileAttribute(key=key, display_name=name, description=desc, data_type=typ,
                                user_editable=editable, built_in=True, sort_order=i,
                                enum_options=USER_TYPES if key == "user_type" else None))
    db.commit()


def catalog(db: Session) -> List[ProfileAttribute]:
    ensure_defaults(db)
    return db.query(ProfileAttribute).order_by(ProfileAttribute.sort_order, ProfileAttribute.id).all()


def by_key(db: Session) -> Dict[str, ProfileAttribute]:
    return {a.key: a for a in catalog(db)}


class AttributeError_(ValueError):
    """Invalid attribute value or definition; the message is safe to show."""


def coerce_value(attr: ProfileAttribute, value: Any) -> Optional[Any]:
    """Validate one value against its definition. Returns None for 'clear this attribute'."""
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None
    t = attr.data_type
    label = attr.display_name
    if t == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in ("true", "false"):
            return value.lower() == "true"
        raise AttributeError_(f"{label} must be true or false")
    if t == "number":
        if isinstance(value, bool):
            raise AttributeError_(f"{label} must be a number")
        try:
            n = float(value)
        except (TypeError, ValueError):
            raise AttributeError_(f"{label} must be a number")
        if n != n or n in (float("inf"), float("-inf")):
            raise AttributeError_(f"{label} must be a number")
        return int(n) if n == int(n) else n
    if not isinstance(value, str):
        raise AttributeError_(f"{label} must be text")
    value = value.strip()
    if len(value) > MAX_STR:
        raise AttributeError_(f"{label} is limited to {MAX_STR} characters")
    if t == "enum":
        if value not in (attr.enum_options or []):
            raise AttributeError_(f"{label} must be one of: {', '.join(attr.enum_options or [])}")
    elif t == "timezone":
        if not valid_timezone(value):
            raise AttributeError_("Time zone must be an IANA time zone such as Europe/London")
    elif t == "locale":
        if not valid_locale(value):
            raise AttributeError_("Locale must look like en or en-GB")
    return value


def validate_values(db: Session, values: Dict[str, Any], *, only_editable_by_user: bool, current: Dict[str, Any]) -> Dict[str, Any]:
    """Return the cleaned changes (None = remove). Unknown attributes are refused; so are admin-managed ones when
    `only_editable_by_user`. A stored legacy value that is submitted unchanged is left alone."""
    defs = by_key(db)
    out: Dict[str, Any] = {}
    for key, raw in values.items():
        attr = defs.get(key)
        if attr is None:
            raise PermissionError_(f"Unknown attribute '{key}'. Define it in the Profile editor first.", 422)
        if only_editable_by_user and not attr.user_editable:
            raise PermissionError_(f"Attribute '{key}' cannot be edited by users", 403)
        if key in current and raw == current[key] and raw is not None:
            out[key] = current[key]  # unchanged legacy/valid value
            continue
        out[key] = coerce_value(attr, raw)
    return out


class PermissionError_(Exception):
    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.message, self.status = message, status
