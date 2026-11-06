"""SCIM PATCH engine (RFC 7644 3.5.2).

Operates on the resource rendered as SCIM JSON. The caller re-validates the result through the same code path as
PUT, so PATCH cannot reach anything PUT cannot. Unknown attributes are ignored (not an error), because IdPs send
attributes we never advertised. Read-only attributes named by an explicit path are a `mutability` error; when they
arrive inside a path-less value object (IdPs echo whole resources) they are ignored.
"""

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from backend.app.scim import filter as flt_mod
from backend.app.scim.errors import ScimError, invalid_path, invalid_syntax, invalid_value, mutability, no_target

MAX_OPERATIONS = 500
MAX_PATH = 500
_PATH = re.compile(r"^([A-Za-z][A-Za-z0-9_$\-]*)(?:\[(.*)\])?(?:\.([A-Za-z][A-Za-z0-9_$\-]*))?$", re.S)


@dataclass
class AttrDef:
    subs: Tuple[str, ...] = ()
    multi: bool = False
    readonly: bool = False


class PatchSchema:
    def __init__(self, core: Dict[str, AttrDef], extensions: Optional[Dict[str, Dict[str, AttrDef]]] = None, core_urn: str = ""):
        self.core_urn = core_urn
        self.core = core
        self.ext = extensions or {}
        self._core_l = {k.lower(): k for k in core}
        self._ext_l = {u.lower(): u for u in self.ext}
        self._ext_attr_l = {u: {k.lower(): k for k in d} for u, d in self.ext.items()}

    def defs(self, urn: Optional[str]) -> Dict[str, AttrDef]:
        return self.ext[urn] if urn else self.core

    def canon(self, urn: Optional[str], attr: str) -> Optional[str]:
        table = self._ext_attr_l[urn] if urn else self._core_l
        return table.get(attr.lower())

    def split(self, path: str) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        """-> (extension urn, attribute, filter text, sub-attribute). attribute None = the extension object itself."""
        if len(path) > MAX_PATH:
            raise invalid_path("Path is too long")
        urn, rest = None, path
        low = path.lower()
        for ul, u in self._ext_l.items():
            if low.startswith(ul):
                tail = path[len(ul):]
                if tail == "":
                    return u, None, None, None
                if tail[0] == ":":
                    urn, rest = u, tail[1:]
                    break
        if urn is None and self.core_urn and low.startswith(self.core_urn.lower() + ":"):
            rest = path[len(self.core_urn) + 1:]
        m = _PATH.match(rest)
        if not m:
            raise invalid_path("Invalid path")
        return urn, m.group(1), m.group(2), m.group(3)


# ---- filter evaluation on a python dict (value paths) -------------------------------------------

def _val(item: Dict[str, Any], key: str):
    for k, v in item.items():
        if k.lower() == key.lower():
            return v
    return None


def _norm(v):
    if isinstance(v, str) and v.lower() in ("true", "false"):
        return v.lower() == "true"
    return v.lower() if isinstance(v, str) else v


def _match(node, item: Dict[str, Any]) -> bool:
    kind = node[0]
    if kind == "and":
        return _match(node[1], item) and _match(node[2], item)
    if kind == "or":
        return _match(node[1], item) or _match(node[2], item)
    have = _val(item, node[1])
    if kind == "pr":
        return have not in (None, "", [])
    _, _, op, want = node
    h, w = _norm(have), _norm(want)
    if op == "eq":
        return h == w
    if op == "ne":
        return h != w
    if not isinstance(h, str) or not isinstance(w, str):
        return False
    return {"co": w in h, "sw": h.startswith(w), "ew": h.endswith(w)}[op]


def _seed(node) -> Optional[Dict[str, Any]]:
    if node[0] == "cmp" and node[2] == "eq":
        return {node[1]: node[3]}
    if node[0] == "and":
        a, b = _seed(node[1]), _seed(node[2])
        return {**a, **b} if a is not None and b is not None else None
    return None


# ---- operations -----------------------------------------------------------------------------

def apply_patch(schema: PatchSchema, doc: Dict[str, Any], operations: Any) -> Dict[str, Any]:
    if not isinstance(operations, list) or not operations:
        raise invalid_syntax("Operations must be a non-empty array")
    if len(operations) > MAX_OPERATIONS:
        raise ScimError(413, f"At most {MAX_OPERATIONS} operations per request", "tooMany")
    for o in operations:
        if not isinstance(o, dict):
            raise invalid_syntax("Each operation must be an object")
        op = str(o.get("op", "")).lower()
        if op not in ("add", "replace", "remove"):
            raise invalid_syntax("op must be add, replace or remove")
        path = o.get("path")
        if op != "remove" and "value" not in o:
            raise invalid_value("value is required")
        if path is None or path == "":
            if op == "remove":
                raise no_target("remove requires a path")
            if not isinstance(o["value"], dict):
                raise invalid_value("value must be an object when path is omitted")
            for k, v in o["value"].items():
                _apply_one(schema, doc, op, str(k), v, pathless=True)
        else:
            if not isinstance(path, str):
                raise invalid_path("path must be a string")
            _apply_one(schema, doc, op, path, o.get("value"), pathless=False)
    return doc


def _apply_one(schema: PatchSchema, doc, op: str, path: str, value, *, pathless: bool) -> None:
    urn, attr, flt, sub = schema.split(path)
    if attr is None:  # the whole extension object
        if op == "remove":
            doc.pop(urn, None)
            return
        if not isinstance(value, dict):
            raise invalid_value("Extension value must be an object")
        for k, v in value.items():
            _apply_one(schema, doc, op, f"{urn}:{k}", v, pathless=pathless)
        return
    canon = schema.canon(urn, attr)
    if canon is None:
        if attr.lower() in ("id", "meta") and not pathless:
            raise mutability(f"'{attr}' is read-only")
        return  # not a mapped attribute: ignored
    d = schema.defs(urn)[canon]
    if d.readonly:
        if pathless:
            return
        raise mutability(f"'{canon}' is read-only")
    if urn:
        container = doc.setdefault(urn, {})
        if not isinstance(container, dict):
            container = doc[urn] = {}
    else:
        container = doc
    subs = {s.lower(): s for s in d.subs}
    csub = None
    if sub is not None:
        csub = subs.get(sub.lower())
        if csub is None:
            return  # unknown sub-attribute: ignored
    if flt is not None:
        if not d.multi:
            raise invalid_path(f"'{canon}' is not multi-valued")
        return _filtered(container, canon, flt, csub, op, value, subs)
    if csub is not None:
        return _sub(container, canon, d, csub, op, value)
    _whole(container, canon, d, subs, op, value)


def _items(value, d: AttrDef) -> List[Any]:
    items = value if isinstance(value, list) else [value]
    out = []
    for it in items:
        if isinstance(it, dict):
            out.append(dict(it))
        elif "value" in {s.lower() for s in d.subs}:
            out.append({"value": it})
        else:
            out.append(it)
    return out


def _whole(container, canon, d: AttrDef, subs, op, value) -> None:
    if op == "remove":
        if d.multi and value is not None:
            drop = {str(x.get("value")) if isinstance(x, dict) else str(x) for x in _items(value, d)}
            container[canon] = [e for e in container.get(canon) or [] if str(_val(e, "value")) not in drop]
        else:
            container.pop(canon, None)
        return
    if d.multi:
        items = _items(value, d)
        if op == "replace":
            container[canon] = items
        else:
            cur = container.get(canon) or []
            container[canon] = cur + [i for i in items if i not in cur]
        return
    if d.subs:  # complex single-valued: merge sub-attributes
        if isinstance(value, str) and "value" in subs:
            value = {"value": value}
        if not isinstance(value, dict):
            raise invalid_value(f"'{canon}' must be an object")
        cur = container.get(canon)
        cur = dict(cur) if isinstance(cur, dict) else {}
        for k, v in value.items():
            cs = subs.get(str(k).lower())
            if cs:
                cur[cs] = v
        container[canon] = cur
        return
    if isinstance(value, (dict, list)):
        raise invalid_value(f"'{canon}' must be a simple value")
    container[canon] = value


def _sub(container, canon, d: AttrDef, csub, op, value) -> None:
    if d.multi:
        lst = container.get(canon) or []
        if op == "remove":
            for e in lst:
                e.pop(csub, None)
        elif not lst:
            container[canon] = [{csub: value}]
        else:
            for e in lst:
                e[csub] = value
        return
    cur = container.get(canon)
    cur = cur if isinstance(cur, dict) else {}
    if op == "remove":
        cur.pop(csub, None)
    else:
        cur[csub] = value
    container[canon] = cur


def _filtered(container, canon, flt_text, csub, op, value, subs) -> None:
    try:
        node = flt_mod.parse(flt_text)
    except ScimError as e:
        raise invalid_path(f"Invalid path filter: {e.detail}")
    lst = container.get(canon) or []
    matches = [e for e in lst if isinstance(e, dict) and _match(node, e)]
    if op == "remove":
        if csub:
            for e in matches:
                e.pop(csub, None)
        else:
            ids = {id(e) for e in matches}
            container[canon] = [e for e in lst if id(e) not in ids]
        return
    if csub is None and not isinstance(value, dict):
        raise invalid_value("value must be an object")
    if matches:
        for e in matches:
            if csub:
                e[csub] = value
            else:
                e.clear()
                e.update(value)
        return
    seed = _seed(node)
    if seed is None:
        raise no_target("No element matches the path filter")
    elem = {(subs.get(k.lower()) or k): v for k, v in seed.items()}
    if csub:
        elem[csub] = value
    else:
        elem.update(value)
    container[canon] = lst + [elem]
