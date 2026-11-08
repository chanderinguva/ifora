"""Talking to the app (ADR 009 D3, D5): a SCIM 2.0 client and a REST gateway behind one interface.

Both use the recipe engine's SSRF-safe HTTP client (validated public IP, no redirects, size and time caps). Failures
are either `Retryable` (network, 429, 5xx: backoff and try again) or `Permanent` (the app said no: an admin must look).
"""

import base64
import json
import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from backend.app.recipes import http_client as hc
from backend.app.recipes.redact import redact_text

http_overrides: Dict[str, Any] = {}  # tests inject {"policy", "resolver", "transport"}

REST_OPS = ("test", "find_user", "create_user", "update_user", "deactivate_user", "reactivate_user", "delete_user",
            "create_group", "update_group", "delete_group")
_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
_PH = re.compile(r"\{\{\s*([A-Za-z0-9_.\[\]:\-]{1,200})\s*\}\}")


class Retryable(Exception):
    def __init__(self, message: str, retry_after: Optional[int] = None):
        super().__init__(message)
        self.retry_after = retry_after


class Permanent(Exception):
    pass


class Conflict(Permanent):
    """The app already has this resource (SCIM 409)."""


class NotFound(Permanent):
    pass


def _clip(text: str, n: int = 300) -> str:
    return text[:n]


def _detail(res: hc.HttpResult) -> str:
    try:
        body = json.loads(res.body.decode("utf-8", "replace"))
        if isinstance(body, dict):
            msg = body.get("detail") or body.get("message") or body.get("error_description") or body.get("error") or ""
            if isinstance(msg, (str, int)):
                return _clip(redact_text(str(msg)))
    except ValueError:
        pass
    return _clip(redact_text(res.body.decode("utf-8", "replace")[:200]))


class Http:
    """Authenticated JSON calls against `base_url`."""

    def __init__(self, base_url: str, auth_type: str, secret: str, header_name: Optional[str], content_type: str):
        self.base = base_url.rstrip("/")
        self.content_type = content_type
        self.headers = {"Accept": "application/json, application/scim+json"}
        if auth_type == "bearer":
            self.headers["Authorization"] = f"Bearer {secret}"
        elif auth_type == "basic":
            self.headers["Authorization"] = "Basic " + base64.b64encode(secret.encode()).decode()
        elif auth_type == "header" and header_name:
            self.headers[header_name] = secret

    def call(self, method: str, path: str, body: Any = None, ok=(200, 201, 202, 204), allow=()) -> hc.HttpResult:
        if not path.startswith("/") or path.startswith("//") or "\r" in path or "\n" in path:
            raise Permanent("invalid request path")
        headers = dict(self.headers)
        data = None
        if body is not None:
            data = json.dumps(body, separators=(",", ":")).encode()
            headers["Content-Type"] = self.content_type
        try:
            res = hc.safe_request(
                method, self.base + path, headers, data, policy=http_overrides.get("policy"),
                resolver=http_overrides.get("resolver"), transport=http_overrides.get("transport"),
            )
        except hc.EgressBlocked as e:
            raise Permanent(f"destination not allowed: {_clip(str(e), 120)}") from e
        except hc.ResponseTooLarge as e:
            raise Permanent("the app's response was too large") from e
        except hc.HttpFailure as e:
            raise Retryable(str(e)) from e
        if res.status in ok or res.status in allow:
            return res
        msg = f"HTTP {res.status}: {_detail(res)}".rstrip(": ")
        if res.status == 429:
            ra = res.headers.get("retry-after", "")
            raise Retryable(msg, int(ra) if ra.isdigit() else None)
        if res.status >= 500 or res.status == 408:
            raise Retryable(msg)
        if res.status == 404:
            raise NotFound(msg)
        if res.status == 409:
            raise Conflict(msg)
        raise Permanent(msg)


def _json(res: hc.HttpResult) -> Any:
    try:
        return json.loads(res.body.decode("utf-8")) if res.body else None
    except ValueError:
        return None


def _rid(value: Any) -> str:
    if isinstance(value, (str, int)) and not isinstance(value, bool) and 0 < len(str(value)) <= 255:
        return str(value)
    raise Permanent("the app did not return an id")


class Adapter:
    supports_groups = False

    def test(self) -> str: ...
    def find_user(self, doc: dict) -> Optional[str]: ...
    def create_user(self, doc: dict) -> str: ...
    def update_user(self, rid: str, doc: dict) -> None: ...
    def set_active(self, rid: str, doc: dict, active: bool) -> None: ...
    def delete_user(self, rid: str) -> None: ...
    def find_group(self, doc: dict) -> Optional[str]: ...
    def create_group(self, doc: dict) -> str: ...
    def update_group(self, rid: str, doc: dict) -> None: ...
    def delete_group(self, rid: str) -> None: ...


def _esc(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"')


class ScimAdapter(Adapter):
    supports_groups = True

    def __init__(self, http: Http, options: dict):
        self.h = http
        self.put = (options or {}).get("update_style", "put") != "patch"

    def test(self) -> str:
        try:
            self.h.call("GET", "/ServiceProviderConfig")
            return "Connected: ServiceProviderConfig answered"
        except NotFound:
            self.h.call("GET", "/Users?count=1")  # ServiceProviderConfig is optional in practice
            return "Connected: /Users answered"

    def _find(self, resource: str, attr: str, value: str) -> Optional[str]:
        res = self.h.call("GET", f"/{resource}?filter=" + quote(f'{attr} eq "{_esc(value)}"', safe=""))
        body = _json(res)
        items = body.get("Resources") if isinstance(body, dict) else None
        return _rid(items[0].get("id")) if items else None

    def find_user(self, doc: dict) -> Optional[str]:
        return self._find("Users", "userName", doc["userName"])

    def create_user(self, doc: dict) -> str:
        body = _json(self.h.call("POST", "/Users", doc))
        return _rid(body.get("id") if isinstance(body, dict) else None)

    def update_user(self, rid: str, doc: dict) -> None:
        p = f"/Users/{quote(rid, safe='')}"
        if self.put:
            self.h.call("PUT", p, {**doc, "id": rid})
        else:
            ops = [{"op": "replace", "value": {k: v for k, v in doc.items() if k not in ("schemas", "id")}}]
            self.h.call("PATCH", p, {"schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"], "Operations": ops})

    def set_active(self, rid: str, doc: dict, active: bool) -> None:
        self.h.call("PATCH", f"/Users/{quote(rid, safe='')}", {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "replace", "path": "active", "value": bool(active)}]})

    def delete_user(self, rid: str) -> None:
        try:
            self.h.call("DELETE", f"/Users/{quote(rid, safe='')}")
        except NotFound:
            pass

    def find_group(self, doc: dict) -> Optional[str]:
        return self._find("Groups", "displayName", doc["displayName"])

    def create_group(self, doc: dict) -> str:
        body = _json(self.h.call("POST", "/Groups", doc))
        return _rid(body.get("id") if isinstance(body, dict) else None)

    def update_group(self, rid: str, doc: dict) -> None:
        self.h.call("PUT", f"/Groups/{quote(rid, safe='')}", {**doc, "id": rid})

    def delete_group(self, rid: str) -> None:
        try:
            self.h.call("DELETE", f"/Groups/{quote(rid, safe='')}")
        except NotFound:
            pass


# ---- REST gateway ----------------------------------------------------------------------------------------------

def lookup(doc: Any, path: str) -> Any:
    """`userName`, `name.givenName`, `emails[0].value`, `urn:...:2.0:User.department`, or a response path like `data.0.id`."""
    node = doc
    if path.startswith("urn:") and isinstance(doc, dict):
        key = next((k for k in doc if path.startswith(k + ".")), None)
        if key is None:
            return None
        node, path = doc[key], path[len(key) + 1:]
    for part in re.findall(r"[^.\[\]]+", path):
        if isinstance(node, dict):
            node = node.get(part)
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            return None
    return node


def render(template: Any, ctx: dict, *, quote_strings: bool = False) -> Any:
    """Fill `{{placeholders}}` from `ctx`. A string that is exactly one placeholder keeps the value's type (booleans,
    numbers); otherwise values are interpolated as text (URL-encoded when `quote_strings`)."""
    if isinstance(template, dict):
        return {k: render(v, ctx) for k, v in template.items()}
    if isinstance(template, list):
        return [render(v, ctx) for v in template]
    if not isinstance(template, str):
        return template
    whole = _PH.fullmatch(template.strip())
    if whole and not quote_strings:
        return lookup(ctx, whole.group(1))

    def sub(m):
        v = lookup(ctx, m.group(1))
        s = "" if v is None else (str(v).lower() if isinstance(v, bool) else str(v))
        return quote(s, safe="") if quote_strings else s

    return _PH.sub(sub, template)


def validate_rest_config(cfg: Any) -> Dict[str, Any]:
    if not isinstance(cfg, dict):
        raise ValueError("rest_config must be an object of operations")
    if set(cfg) - set(REST_OPS):
        raise ValueError("unknown operation: " + ", ".join(sorted(set(cfg) - set(REST_OPS))))
    for need in ("create_user", "deactivate_user"):
        if need not in cfg:
            raise ValueError(f"the gateway needs a '{need}' operation")
    out: Dict[str, Any] = {}
    for name, op in cfg.items():
        if not isinstance(op, dict) or set(op) - {"method", "path", "body", "id_path", "ok"}:
            raise ValueError(f"{name}: expected method, path, body, id_path, ok")
        method, path = str(op.get("method", "")).upper(), str(op.get("path", ""))
        if method not in _METHODS:
            raise ValueError(f"{name}: method must be one of {', '.join(_METHODS)}")
        if not path.startswith("/") or path.startswith("//") or ".." in path or "://" in path or len(path) > 300 or "\n" in path or "\r" in path:
            raise ValueError(f"{name}: path must start with a single '/' and stay on the app's host")
        if name in ("create_user", "create_group") and not op.get("id_path"):
            raise ValueError(f"{name}: id_path (where the app's id is in the response) is required")
        ok = op.get("ok", [200, 201, 202, 204])
        if not isinstance(ok, list) or not ok or not all(isinstance(s, int) and 200 <= s < 300 for s in ok):
            raise ValueError(f"{name}: ok must be a list of 2xx status codes")
        body = op.get("body")
        if body is not None and len(json.dumps(body)) > 8000:
            raise ValueError(f"{name}: body template too large")
        out[name] = {k: v for k, v in {"method": method, "path": path, "body": body, "id_path": op.get("id_path"), "ok": ok}.items() if v is not None}
    return out


class RestGateway(Adapter):
    """Speaks SCIM semantics to the rest of IdentityForge and the app's own REST API to the outside."""

    def __init__(self, http: Http, config: dict):
        self.h, self.cfg = http, config or {}
        self.supports_groups = "create_group" in self.cfg

    def _op(self, name: str, ctx: dict, *, required: bool = True):
        op = self.cfg.get(name)
        if op is None:
            if required:
                raise Permanent(f"the gateway has no '{name}' operation")
            return None
        path = render(op["path"], ctx, quote_strings=True)
        body = render(op["body"], ctx) if "body" in op else None
        res = self.h.call(op["method"], path, body, ok=tuple(op.get("ok", (200, 201, 202, 204))))
        return op, _json(res)

    def test(self) -> str:
        if "test" not in self.cfg:
            return "Saved (no test operation configured)"
        self._op("test", {})
        return "Connected: test operation succeeded"

    def find_user(self, doc: dict) -> Optional[str]:
        if "find_user" not in self.cfg:
            return None
        try:
            op, body = self._op("find_user", doc)
        except NotFound:
            return None
        v = lookup(body, self.cfg["find_user"].get("id_path", "id")) if body is not None else None
        return _rid(v) if v not in (None, "") else None

    def create_user(self, doc: dict) -> str:
        op, body = self._op("create_user", doc)
        return _rid(lookup(body, op["id_path"]))

    def update_user(self, rid: str, doc: dict) -> None:
        if "update_user" in self.cfg:
            self._op("update_user", {**doc, "id": rid})

    def set_active(self, rid: str, doc: dict, active: bool) -> None:
        name = "reactivate_user" if active and "reactivate_user" in self.cfg else ("update_user" if active else "deactivate_user")
        if active and name == "update_user" and "update_user" not in self.cfg:
            raise Permanent("the gateway has neither 'reactivate_user' nor 'update_user'")
        self._op(name, {**doc, "id": rid, "active": active})

    def delete_user(self, rid: str) -> None:
        try:
            self._op("delete_user", {"id": rid})
        except NotFound:
            pass

    def find_group(self, doc: dict) -> Optional[str]:
        return None

    def create_group(self, doc: dict) -> str:
        op, body = self._op("create_group", doc)
        return _rid(lookup(body, op["id_path"]))

    def update_group(self, rid: str, doc: dict) -> None:
        if "update_group" in self.cfg:
            self._op("update_group", {**doc, "id": rid})

    def delete_group(self, rid: str) -> None:
        if "delete_group" in self.cfg:
            try:
                self._op("delete_group", {"id": rid})
            except NotFound:
                pass


def build(app, secret: str) -> Adapter:
    if app.kind == "scim":
        return ScimAdapter(Http(app.base_url, app.auth_type, secret, app.header_name, "application/scim+json"), app.options or {})
    return RestGateway(Http(app.base_url, app.auth_type, secret, app.header_name, "application/json"), app.rest_config or {})
