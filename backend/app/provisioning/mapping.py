"""Ifora user/group -> canonical SCIM 2.0 resource, with per-app overrides (ADR 009 D4).

The canonical resource is what a SCIM app receives as-is and what the REST gateway maps into the app's own JSON.
Sources are an allow-list of user fields and profile attributes: password hashes, MFA data, tokens, roles and
tenant ids are not mappable, so a mapping cannot leak them.
"""

import hashlib
import json
import re
from typing import Any, Dict, List, Optional

from backend.app.scim import mapping as scim_map

USER_URN, ENTERPRISE_URN = scim_map.USER_URN, scim_map.ENTERPRISE_URN
GROUP_URN = scim_map.GROUP_URN
BUILTIN_FIELDS = ("email", "username", "first_name", "last_name", "display_name", "status", "public_id")
IDENTIFIERS = ("email", "username")
MAX_RULES = 60
_TARGET = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,40}(\.[A-Za-z][A-Za-z0-9_]{0,40}){0,3}$")
_URN_TARGET = re.compile(r"^urn:[A-Za-z0-9:._-]{3,150}:[A-Za-z][A-Za-z0-9_]{0,40}(\.[A-Za-z][A-Za-z0-9_]{0,40}){0,2}$")
_URN_SPLIT = re.compile(r"^(urn:.+:[A-Za-z0-9_-]+)\.([A-Za-z][A-Za-z0-9_.]*)$")  # extension URN, then the attribute path
_PLACEHOLDER = re.compile(r"\{\{\s*([a-z][a-z0-9_]{0,60})\s*\}\}")
RESERVED_TARGETS = {"schemas", "id", "meta", "groups", "password", "userName", "active", "externalId"}  # set by Ifora only


class MappingError(ValueError):
    pass


def source_fields(profile_keys: List[str]) -> List[str]:
    return list(BUILTIN_FIELDS) + sorted(profile_keys)


def validate_rules(rules: Any, profile_keys: List[str]) -> List[Dict[str, str]]:
    """Normalise `[{target, source}]`. `source` is a field name or a template such as "{{first_name}} {{last_name}}"."""
    if rules is None:
        return []
    if not isinstance(rules, list) or len(rules) > MAX_RULES:
        raise MappingError(f"mapping must be a list of at most {MAX_RULES} rules")
    allowed = set(source_fields(profile_keys))
    out, seen = [], set()
    for r in rules:
        if not isinstance(r, dict) or set(r) - {"target", "source"}:
            raise MappingError("each rule needs only 'target' and 'source'")
        target, source = str(r.get("target", "")).strip(), str(r.get("source", "")).strip()
        if not (_TARGET.match(target) or _URN_TARGET.match(target)):
            raise MappingError(f"invalid target '{target[:40]}'")
        if target.split(".")[0] in RESERVED_TARGETS or target in RESERVED_TARGETS:
            raise MappingError(f"'{target}' is set by Ifora and cannot be mapped")
        if target in seen:
            raise MappingError(f"target '{target}' is mapped twice")
        if not source or len(source) > 300:
            raise MappingError("source is required (max 300 characters)")
        names = _PLACEHOLDER.findall(source)
        if names:
            bad = [n for n in names if n not in allowed]
            if bad:
                raise MappingError(f"unknown field '{bad[0]}' in template")
        elif source not in allowed:
            raise MappingError(f"unknown source '{source[:40]}'")
        seen.add(target)
        out.append({"target": target, "source": source})
    return out


def _field(user, name: str) -> Any:
    if name == "email":
        return user.email
    if name == "username":
        return user.username
    if name == "first_name":
        return user.first_name
    if name == "last_name":
        return user.last_name
    if name == "display_name":
        return f"{user.first_name} {user.last_name}".strip()
    if name == "status":
        return user.status
    if name == "public_id":
        return user.public_id
    return (user.get_profile_attributes() or {}).get(name)


def _render(source: str, user) -> Any:
    names = _PLACEHOLDER.findall(source)
    if not names:
        return _field(user, source)
    whole = _PLACEHOLDER.fullmatch(source.strip())
    if whole:
        return _field(user, whole.group(1))
    return _PLACEHOLDER.sub(lambda m: str(_field(user, m.group(1)) if _field(user, m.group(1)) is not None else ""), source).strip()


def _set_path(doc: dict, target: str, value: Any) -> None:
    if target.startswith("urn:"):
        m = _URN_SPLIT.match(target)
        if not m:
            raise MappingError(f"invalid target '{target[:40]}'")
        node = doc.setdefault(m.group(1), {})
        keys = m.group(2).split(".")
    else:
        node, keys = doc, target.split(".")
    for k in keys[:-1]:
        node = node.setdefault(k, {})
        if not isinstance(node, dict):
            raise MappingError(f"'{target}' conflicts with another mapping")
    node[keys[-1]] = value


def default_rules() -> List[Dict[str, str]]:
    """The Okta-style baseline. Admins add rules on top (same target replaces the default)."""
    return [
        {"target": "name.givenName", "source": "first_name"},
        {"target": "name.familyName", "source": "last_name"},
        {"target": "displayName", "source": "display_name"},
        {"target": "title", "source": "title"},
        {"target": "locale", "source": "locale"},
        {"target": "timezone", "source": "timezone"},
        {"target": f"{ENTERPRISE_URN}.department", "source": "department"},
        {"target": f"{ENTERPRISE_URN}.costCenter", "source": "cost_center"},
        {"target": f"{ENTERPRISE_URN}.employeeNumber", "source": "employee_number"},
        {"target": f"{ENTERPRISE_URN}.organization", "source": "organization"},
        {"target": f"{ENTERPRISE_URN}.division", "source": "division"},
        {"target": f"{ENTERPRISE_URN}.manager.value", "source": "manager"},
    ]


def user_resource(user, app, *, active: bool = True) -> Dict[str, Any]:
    """The SCIM User this app should hold for `user`."""
    opts = app.options or {}
    ident = opts.get("user_identifier", "email")
    doc: Dict[str, Any] = {"schemas": [USER_URN], "externalId": user.public_id,
                           "userName": user.email if ident == "email" else user.username, "active": bool(active),
                           "emails": [{"value": user.email, "type": "work", "primary": True}]}
    rules = {r["target"]: r for r in default_rules()}
    for r in app.mapping or []:
        rules[r["target"]] = r
    for target, r in rules.items():
        value = _render(r["source"], user)
        if value in (None, ""):
            continue
        _set_path(doc, target, value)
    phone = (user.get_profile_attributes() or {}).get("primary_phone")
    if phone and "phoneNumbers" not in doc:
        doc["phoneNumbers"] = [{"value": phone, "type": "work", "primary": True}]
    urns = [k for k in doc if k.startswith("urn:")]
    doc["schemas"] = [USER_URN] + sorted(urns)
    return doc


def group_resource(group, member_remote_ids: List[str]) -> Dict[str, Any]:
    return {"schemas": [GROUP_URN], "externalId": group.public_id, "displayName": group.name,
            "members": [{"value": m} for m in member_remote_ids]}


def payload_hash(doc: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
