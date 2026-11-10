"""Generic connector engine (ADR 026): validate inputs, build one request from a definition, send it through the shared egress path, map the reply.

Safety rules enforced here, whatever a definition says:
- the host comes from the definition plus validated connection config, never from an input;
- every placeholder value is percent-encoded as a single path segment or query value, so an input cannot add segments, parameters or headers;
- "." and ".." segments and control characters are refused;
- the request goes through `safe_request` (resolve-then-connect, private ranges blocked, no redirects, size and time limits);
- secrets are scrubbed from everything returned.
"""

import base64
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote

from backend.app.connectors.schema import Action, Connector, Input, placeholders
from backend.app.recipes.http_client import EgressBlocked, EgressPolicy, HttpFailure, ResponseTooLarge, safe_request, validate_url
from backend.app.recipes.redact import redact, scrub

_CTRL = re.compile(r"[\x00-\x1f\x7f]")
_CTRL_TEXT = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")   # multiline text may also hold \t \n \r
_FULL = re.compile(r"^\{([a-z][a-z0-9_]*)\}$")
_HOST = re.compile(r"^[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?$")
MAX_JSON_BYTES = 65536
MAX_LIST = 100
MAX_STR = 2000


class ConnectorError(Exception):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.message, self.retryable = message, retryable


@dataclass
class Prepared:
    method: str
    host: str
    path_and_query: str
    headers: Dict[str, str]
    body: Optional[bytes]
    scope_prefix: str

    @property
    def url(self) -> str:
        return f"https://{self.host}{self.path_and_query}"


@dataclass
class Result:
    request: dict
    outputs: dict
    status: Optional[int]
    extra: dict = field(default_factory=dict)


# inputs and config -----------------------------------------------------------------------------------------------------------

def _clean(v: str, what: str) -> str:
    if _CTRL.search(v):
        raise ConnectorError(f"{what} contains control characters")
    return v


def validate_inputs(action: Action, raw: Dict[str, Any], *, partial: bool = False) -> Dict[str, Any]:
    """Coerce and check the (already rendered) inputs against the action's declaration. Unknown inputs are refused.
    `partial` checks only the values given (no required or default handling): used at save time for literal values."""
    raw = raw or {}
    known = {i.key: i for i in action.inputs}
    for k in raw:
        if k not in known:
            raise ConnectorError(f"unknown input '{k}'")
    out: Dict[str, Any] = {}
    for i in action.inputs:
        v = raw.get(i.key)
        if partial and i.key not in raw:
            continue
        if v is None or (isinstance(v, str) and v == ""):
            if i.default is not None:
                v = i.default
            elif i.required:
                raise ConnectorError(f"'{i.label}' is required")
            else:
                continue
        out[i.key] = _coerce(i, v)
    return out


def _coerce(i: Input, v: Any) -> Any:
    if i.type == "boolean":
        if isinstance(v, bool):
            return v
        if isinstance(v, str) and v.lower() in ("true", "false"):
            return v.lower() == "true"
        raise ConnectorError(f"'{i.label}' must be true or false")
    if i.type == "integer":
        if isinstance(v, bool) or not (isinstance(v, int) or (isinstance(v, str) and re.fullmatch(r"-?\d{1,12}", v.strip()))):
            raise ConnectorError(f"'{i.label}' must be a whole number")
        n = int(v)
        if not (i.minimum <= n <= i.maximum):
            raise ConnectorError(f"'{i.label}' must be between {i.minimum} and {i.maximum}")
        return n
    if isinstance(v, bool) or not isinstance(v, (str, int)):
        raise ConnectorError(f"'{i.label}' must be text")
    s = str(v)
    if (_CTRL_TEXT if i.multiline else _CTRL).search(s):
        raise ConnectorError(f"'{i.label}' contains control characters")
    if len(s) > i.max_length:
        raise ConnectorError(f"'{i.label}' is longer than {i.max_length} characters")
    if i.type == "select":
        if s not in i.options:
            raise ConnectorError(f"'{i.label}' must be one of: {', '.join(i.options)}")
        return s
    if i.pattern and not re.fullmatch(i.pattern, s):
        raise ConnectorError(f"'{i.label}' has an invalid format")
    if s in (".", ".."):
        raise ConnectorError(f"'{i.label}' has an invalid format")
    return s


def validate_config(c: Connector, config: Dict[str, Any], secrets: Dict[str, Any], *, partial_secrets: bool = False) -> Tuple[dict, dict]:
    """Check what an administrator typed into the Connect form. Returns (config, secrets). Never echoes secret values in errors."""
    config, secrets = dict(config or {}), dict(secrets or {})
    fields = {f.key: f for f in c.auth.fields}
    for k in list(config) + list(secrets):
        if k not in fields:
            raise ConnectorError(f"unknown field '{k}'")
    out_cfg, out_sec = {}, {}
    for f in c.auth.fields:
        bag, dest = (secrets, out_sec) if f.secret else (config, out_cfg)
        if f.secret and f.key in config or (not f.secret and f.key in secrets):
            raise ConnectorError(f"'{f.label}' is in the wrong place")
        v = bag.get(f.key)
        if v is None or v == "":
            if f.secret and partial_secrets:
                continue
            raise ConnectorError(f"'{f.label}' is required")
        if not isinstance(v, str):
            raise ConnectorError(f"'{f.label}' must be text")
        if _CTRL.search(v) or len(v) > f.max_length:
            raise ConnectorError(f"'{f.label}' is not valid")
        if not f.secret and not re.fullmatch(f.pattern, v):
            raise ConnectorError(f"'{f.label}' has an invalid format")
        dest[f.key] = v
    return out_cfg, out_sec


# request building --------------------------------------------------------------------------------------------------------------

def resolve_host(c: Connector, config: Dict[str, Any]) -> str:
    template = c.hosts[0]
    host = template
    for p in placeholders(template):
        host = host.replace("{" + p + "}", str(config.get(p, "")))
    host = host.lower()
    if not _HOST.match(host) or host.count(".") != template.count(".") or any(x in host for x in ("..", "{", "}")):
        raise ConnectorError("the connection's settings do not give a valid host")
    return host


def _subst(text: str, values: Dict[str, Any], encode: Callable[[str], str]) -> str:
    def rep(m):
        k = m.group(1)
        if k not in values:
            raise ConnectorError(f"missing value for {k}")
        return encode(str(values[k]))
    return re.sub(r"\{([a-z][a-z0-9_]*)\}", rep, text)


def _seg(s: str) -> str:
    if s in (".", "..") or _CTRL.search(s):
        raise ConnectorError("invalid value in the request path")
    return quote(s, safe="")


def _body(node: Any, values: Dict[str, Any]) -> Any:
    if isinstance(node, str):
        m = _FULL.match(node)
        if m:
            return values.get(m.group(1), _MISSING)
        return _subst(node, values, lambda s: s)
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            r = _body(v, values)
            if r is not _MISSING:
                out[_subst(k, values, lambda s: s)] = r
        return out
    if isinstance(node, list):
        return [r for r in (_body(v, values) for v in node) if r is not _MISSING]
    return node


_MISSING = object()


def _auth_headers(c: Connector, config: Dict[str, Any], secrets: Dict[str, Any]) -> Dict[str, str]:
    a = c.auth
    try:
        if a.scheme == "bearer":
            return {"Authorization": "Bearer " + _clean(secrets["token"], "token")}
        if a.scheme == "basic":
            raw = f"{config['username']}:{secrets['password']}".encode()
            return {"Authorization": "Basic " + base64.b64encode(raw).decode()}
        return {a.header_name: a.header_prefix + _clean(secrets["value"], "value")}
    except KeyError:
        raise ConnectorError("the connection is missing a credential; edit it and enter the secret again")


def _base_headers(c: Connector, config: Dict[str, Any]) -> Dict[str, str]:
    """Static headers plus those filled from the connection's non-secret fields (already checked for control characters)."""
    h = dict(c.headers)
    for k, tmpl in c.config_headers.items():
        h[k] = _subst(tmpl, config, lambda x: x)
    return h


def _scope(path_template: str) -> str:
    return "/" + path_template.split("/")[1]


def build(c: Connector, a: Action, config: Dict[str, Any], inputs: Dict[str, Any], secrets: Optional[Dict[str, Any]]) -> Prepared:
    """One request, fully encoded. `secrets=None` builds the request without credentials (dry run, logging)."""
    values = {**{k: v for k, v in config.items()}, **inputs}
    host = resolve_host(c, config)
    path = _subst(a.path, values, _seg)
    query_parts = []
    for k, tmpl in a.query.items():
        m = _FULL.match(tmpl)
        if m and m.group(1) not in values:
            continue
        query_parts.append(f"{quote(k, safe='')}={_subst(tmpl, values, lambda s: quote(s, safe=''))}")
    pq = path + ("?" + "&".join(query_parts) if query_parts else "")
    headers = _base_headers(c, config)
    body = None
    if a.body is not None:
        body = json.dumps(_body(a.body, values)).encode()
        headers["Content-Type"] = "application/json"
    if secrets is not None:
        headers.update(_auth_headers(c, config, secrets))
    return Prepared(a.method, host, pq, headers, body, _scope(a.path))


# output mapping --------------------------------------------------------------------------------------------------------------

_TOKEN = re.compile(r"\.([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]|\[(\*)\]")


def extract(path: str, data: Any) -> Any:
    """Tiny JSONPath: $.a.b, $.a[0].b, $[*].x (a list of x for every item). Missing parts give None."""
    nodes = [data]
    listed = False
    for m in _TOKEN.finditer(path[1:]):
        name, idx, star = m.groups()
        nxt = []
        for n in nodes:
            if name is not None and isinstance(n, dict) and name in n:
                nxt.append(n[name])
            elif idx is not None and isinstance(n, list) and int(idx) < len(n):
                nxt.append(n[int(idx)])
            elif star and isinstance(n, list):
                nxt.extend(n[:MAX_LIST])
                listed = True
        if not nxt and not star:
            return None
        nodes = nxt
    if listed:
        return nodes[:MAX_LIST]
    return nodes[0] if nodes else None


def _limit(v: Any, depth: int = 0) -> Any:
    if isinstance(v, str):
        return v[:MAX_STR]
    if isinstance(v, (bool, int, float)) or v is None:
        return v
    if depth >= 3:
        return None
    if isinstance(v, list):
        return [_limit(x, depth + 1) for x in v[:MAX_LIST]]
    if isinstance(v, dict):
        return {str(k)[:60]: _limit(x, depth + 1) for k, x in list(v.items())[:50]}
    return None


def map_outputs(a: Action, status: int, parsed: Any) -> dict:
    out: Dict[str, Any] = {"status_code": status, "ok": 200 <= status < 300}
    for o in a.outputs:
        out[o.key] = _limit(extract(o.from_, parsed)) if parsed is not None else None
    return out


# sending -----------------------------------------------------------------------------------------------------------------------

def _send(c: Connector, a_idempotent: bool, a_errors: Dict[int, str], p: Prepared, secret_values: List[str], policy: Optional[EgressPolicy],
          resolver=None, transport=None, body_errors: Optional[Dict[str, str]] = None) -> Tuple[int, Any]:
    try:
        _, host, _, path = validate_url(p.url, policy or EgressPolicy.from_settings())
        if host != p.host or not (path.split("?", 1)[0] == p.scope_prefix or path.startswith(p.scope_prefix + "/")):
            raise ConnectorError("the request left the connector's allowed host or path")
        res = safe_request(p.method, p.url, p.headers, p.body, policy=policy, resolver=resolver, transport=transport)
    except EgressBlocked as e:
        raise ConnectorError(f"blocked: {e}")
    except ResponseTooLarge:
        raise ConnectorError("the response was too large")
    except HttpFailure as e:
        raise ConnectorError(str(e), retryable=a_idempotent)
    parsed = None
    if "json" in (res.content_type or "").lower() and 0 < len(res.body) <= MAX_JSON_BYTES:
        try:
            parsed = json.loads(res.body.decode("utf-8", errors="replace"))
        except ValueError:
            parsed = None
    if res.status < 300:
        if c.reply is not None:
            _check_reply(c, a_idempotent, parsed, body_errors or {})
        return res.status, parsed
    if res.status in a_errors:
        raise ConnectorError(a_errors[res.status], retryable=False)
    if res.status == 429 or res.status >= 500:
        raise ConnectorError(f"{c.name} answered {res.status}", retryable=a_idempotent)
    if res.status < 400:
        raise ConnectorError(f"{c.name} answered {res.status} (redirects are not followed)")
    raise ConnectorError(f"{c.name} answered {res.status}")


_CODE = re.compile(r"[a-z][a-z0-9_]{1,60}")


def _check_reply(c: Connector, retryable_ok: bool, parsed: Any, body_errors: Dict[str, str]) -> None:
    """APIs that answer 200 and put failure in the body: success only when the definition's `ok` field is exactly true."""
    if not isinstance(parsed, dict):
        raise ConnectorError(f"{c.name} sent a reply that could not be read")
    if extract(c.reply.ok, parsed) is True:
        return
    code = extract(c.reply.error, parsed)
    code = code if isinstance(code, str) and _CODE.fullmatch(code) else "unknown_error"   # never echo free text from the remote
    if code in body_errors:
        raise ConnectorError(body_errors[code], retryable=retryable_ok and code in c.reply.retry_codes)
    raise ConnectorError(f"{c.name} refused the request ({code}).", retryable=retryable_ok and code in c.reply.retry_codes)


def _summary(c: Connector, a_id: str, p: Prepared, conn_name: str, secret_values: List[str]) -> dict:
    d = {"connector": c.id, "action": a_id, "method": p.method, "url": p.url, "connection": conn_name,
         "body": p.body.decode(errors="replace")[:2000] if p.body else None}
    return redact(scrub(d, secret_values))


def run_action(c: Connector, a: Action, conn_name: str, config: Dict[str, Any], secrets: Dict[str, Any], raw_inputs: Dict[str, Any], *, dry: bool,
               policy: Optional[EgressPolicy] = None, resolver=None, transport=None) -> Result:
    inputs = validate_inputs(a, raw_inputs)
    secret_values = [v for v in secrets.values() if isinstance(v, str)]
    p = build(c, a, config, inputs, None if dry else secrets)
    summary = _summary(c, a.id, p, conn_name, secret_values)
    if dry:
        return Result(summary, {"dry_run": True, "status_code": None, "ok": None, **{o.key: None for o in a.outputs}}, None)
    status, parsed = _send(c, a.idempotent or a.read_only, a.errors, p, secret_values, policy, resolver, transport, a.body_errors)
    out = redact(scrub(map_outputs(a, status, parsed), secret_values))
    return Result(summary, out, status)


def check_connection(c: Connector, config: Dict[str, Any], secrets: Dict[str, Any], *, policy=None, resolver=None, transport=None) -> Tuple[bool, Optional[int], str]:
    """The definition's test request. Never raises for remote problems: returns (ok, status, message)."""
    path = _subst(c.test.path, config, _seg)
    try:
        p = Prepared("GET", resolve_host(c, config), path, {**_base_headers(c, config), **_auth_headers(c, config, secrets)}, None, _scope(c.test.path))
        status, _ = _send(c, True, {401: "The credentials were refused.", 403: "The credentials were accepted but may not use this resource.",
                                    404: "Not found: check the organisation or account name."}, p, list(secrets.values()), policy, resolver, transport)
        return True, status, "Connected."
    except ConnectorError as e:
        return False, None, e.message
