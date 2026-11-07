"""`attributes` / `excludedAttributes` (RFC 7644 3.4.2.5): trim a rendered resource or list response.

`id` and `schemas` are always returned. Names are case-insensitive, dotted for sub-attributes, and may carry a schema
URN prefix (`urn:...:enterprise:2.0:User:department`). Unknown names are ignored.
"""

import copy
from typing import Any, Dict, List, Optional, Tuple

from backend.app.scim.errors import ScimError

ALWAYS = {"id", "schemas"}
Path = Tuple[Optional[str], List[str]]  # (extension urn or None for the core schema, attribute path)


def parse(raw: Optional[str]) -> List[str]:
    return [n.strip() for n in (raw or "").split(",") if n.strip()]


def _split(name: str, schemas: List[str]) -> Path:
    if name.lower().startswith("urn:"):
        for urn in sorted(schemas, key=len, reverse=True):
            if name.lower().startswith(urn.lower()):
                rest = name[len(urn):].lstrip(":")
                return (urn, [p.lower() for p in rest.split(".") if p])
        return ("", [])  # a schema we do not render: nothing to do
    return (None, [p.lower() for p in name.split(".") if p])


def _key(d: Dict[str, Any], low: str) -> Optional[str]:
    for k in d:
        if k.lower() == low:
            return k
    return None


def _pick(src: Any, path: List[str]) -> Any:
    """Copy only `path` out of src (a dict, or a list of dicts)."""
    if not path:
        return copy.deepcopy(src)
    if isinstance(src, list):
        out = [_pick(e, path) for e in src if isinstance(e, dict)]
        return [e for e in out if e]
    if isinstance(src, dict):
        k = _key(src, path[0])
        if k is None:
            return {}
        sub = _pick(src[k], path[1:])
        return {k: sub} if sub not in ({}, []) else {}
    return {}


def _merge(dst: Dict[str, Any], part: Dict[str, Any]) -> None:
    for k, v in part.items():
        if k in dst and isinstance(dst[k], dict) and isinstance(v, dict):
            _merge(dst[k], v)
        elif k in dst and isinstance(dst[k], list) and isinstance(v, list) and len(dst[k]) == len(v):
            for a, b in zip(dst[k], v):
                if isinstance(a, dict) and isinstance(b, dict):
                    _merge(a, b)
        else:
            dst[k] = v


def _drop(src: Any, path: List[str]) -> None:
    if isinstance(src, list):
        for e in src:
            _drop(e, path)
    elif isinstance(src, dict) and path:
        k = _key(src, path[0])
        if k is None:
            return
        if len(path) == 1:
            del src[k]
        else:
            _drop(src[k], path[1:])


def project_resource(doc: Dict[str, Any], attributes: List[str], excluded: List[str]) -> Dict[str, Any]:
    schemas = [s for s in doc.get("schemas", []) if isinstance(s, str)]
    if attributes:
        out: Dict[str, Any] = {k: copy.deepcopy(v) for k, v in doc.items() if k in ALWAYS}
        for name in attributes:
            urn, path = _split(name, schemas)
            if urn == "" or (urn is None and not path):
                continue
            if urn:
                if not path:
                    if urn in doc:
                        out[urn] = copy.deepcopy(doc[urn])
                elif urn in doc:
                    _merge(out.setdefault(urn, {}), _pick(doc[urn], path))
            else:
                _merge(out, _pick(doc, path))
        return out
    out = copy.deepcopy(doc)
    for name in excluded:
        urn, path = _split(name, schemas)
        if urn == "" or (urn is None and (not path or path[0] in ALWAYS)):
            continue
        if urn:
            if not path:
                out.pop(urn, None)
            elif urn in out:
                _drop(out[urn], path)
        else:
            _drop(out, path)
    return out


def apply(body: Any, attributes: List[str], excluded: List[str]) -> Any:
    if attributes and excluded:
        raise ScimError(400, "Use either attributes or excludedAttributes, not both", "invalidSyntax")
    if not (attributes or excluded) or not isinstance(body, dict):
        return body
    if "Resources" in body:
        body = dict(body)
        body["Resources"] = [project_resource(r, attributes, excluded) for r in body["Resources"]]
        return body
    if "schemas" in body and "id" in body:
        return project_resource(body, attributes, excluded)
    return body
