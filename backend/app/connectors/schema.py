"""Declarative connector definitions and their build-time validation (ADR 026).

A connector is data: which host(s) it may talk to, how it authenticates, and a short list of typed actions. The generic engine in
`engine.py` is the only code that runs them. Definitions ship in the repository (`definitions/*.yaml`) and are checked by
`validate_connector` when the registry loads, so an unsafe definition fails the build and the tests, never production.
"""

import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

_KEY = r"^[a-z][a-z0-9_]{0,31}$"
_PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")
_OUT_PATH = re.compile(r"^\$(\.[A-Za-z_][A-Za-z0-9_]{0,40}|\[\d{1,3}\]|\[\*\]){0,8}$")
_HOST_TEMPLATE = re.compile(r"^[a-z0-9{}][a-z0-9.{}_-]{0,250}[a-z0-9}]$")
_HEADER_NAME = re.compile(r"^[A-Za-z0-9-]{1,100}$")
_FORBIDDEN_HEADERS = {"host", "content-length", "transfer-encoding", "connection", "upgrade", "te", "trailer", "expect", "authorization"}
SCHEMES = ("bearer", "basic", "header")
# the fields every scheme needs (key -> must be secret)
SCHEME_FIELDS = {"bearer": {"token": True}, "basic": {"username": False, "password": True}, "header": {"value": True}}
MAX_ACTIONS = 20


class DefinitionInvalid(ValueError):
    pass


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class AuthField(_Strict):
    key: str = Field(..., pattern=_KEY)
    label: str = Field(..., min_length=1, max_length=80)
    secret: bool = False
    pattern: Optional[str] = Field(None, max_length=200)  # required for non-secret fields: it is what keeps host and path placeholders safe
    max_length: int = Field(200, ge=1, le=2000)


class Auth(_Strict):
    scheme: Literal["bearer", "basic", "header"]
    fields: List[AuthField] = Field(..., min_length=1, max_length=8)
    header_name: Optional[str] = Field(None, max_length=100)  # scheme "header"
    header_prefix: str = Field("", max_length=40)             # e.g. "Token token=" for scheme "header"


class Input(_Strict):
    key: str = Field(..., pattern=_KEY)
    label: str = Field(..., min_length=1, max_length=80)
    type: Literal["string", "integer", "boolean", "select"] = "string"
    required: bool = False
    default: Optional[Any] = None
    pattern: Optional[str] = Field(None, max_length=200)
    max_length: int = Field(200, ge=1, le=2000)
    minimum: Optional[int] = None
    maximum: Optional[int] = None
    options: List[str] = Field(default_factory=list, max_length=50)
    multiline: bool = False   # free text that may hold newlines and tabs; only allowed for inputs used in the JSON body


class Output(_Strict):
    key: str = Field(..., pattern=_KEY)
    from_: str = Field(..., alias="from", max_length=120)


class Action(_Strict):
    id: str = Field(..., pattern=_KEY)
    label: str = Field(..., min_length=1, max_length=80)
    description: str = Field("", max_length=300)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str = Field(..., min_length=2, max_length=300)
    query: Dict[str, str] = Field(default_factory=dict, max_length=10)
    body: Optional[Dict[str, Any]] = None
    inputs: List[Input] = Field(default_factory=list, max_length=15)
    outputs: List[Output] = Field(default_factory=list, max_length=15)
    errors: Dict[int, str] = Field(default_factory=dict, max_length=10)
    body_errors: Dict[str, str] = Field(default_factory=dict, max_length=20)   # messages for the error codes of a reply-level failure (see Connector.reply)
    idempotent: bool = False  # only idempotent actions are retried automatically

    @property
    def read_only(self) -> bool:
        return self.method == "GET"


class Test(_Strict):
    path: str = Field(..., min_length=2, max_length=300)


class Reply(_Strict):
    """For APIs that answer HTTP 200 and report failure in the body (Slack): success only when `ok` is true; `error` holds the code."""
    ok: str = Field(..., max_length=120)
    error: str = Field(..., max_length=120)
    retry_codes: List[str] = Field(default_factory=list, max_length=10)   # error codes worth retrying (only for idempotent or read-only actions)


class Connector(_Strict):
    id: str = Field(..., pattern=r"^[a-z][a-z0-9_]{1,31}$")
    version: int = Field(..., ge=1)
    name: str = Field(..., min_length=1, max_length=60)
    category: str = Field(..., min_length=1, max_length=30)
    description: str = Field("", max_length=300)
    hosts: List[str] = Field(..., min_length=1, max_length=3)
    headers: Dict[str, str] = Field(default_factory=dict, max_length=10)  # static, non-secret request headers (Accept, API version)
    auth: Auth
    test: Test
    reply: Optional[Reply] = None
    actions: List[Action] = Field(..., min_length=1, max_length=MAX_ACTIONS)

    @field_validator("hosts")
    @classmethod
    def _hosts(cls, v):
        for h in v:
            if not _HOST_TEMPLATE.match(h) or "*" in h or ".." in h or h.startswith(".") or "." not in h:
                raise ValueError(f"invalid host template {h!r}")
        return v


def placeholders(text: str) -> List[str]:
    return _PLACEHOLDER.findall(text)


def _walk_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _walk_strings(k)
            yield from _walk_strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk_strings(v)


def _regex(pattern: str, where: str):
    try:
        return re.compile(pattern)
    except re.error as e:
        raise DefinitionInvalid(f"{where}: invalid pattern ({e})")


def _static_prefix_ok(path: str, where: str) -> None:
    if not path.startswith("/") or "//" in path or ".." in path or "?" in path or "#" in path or "\\" in path or " " in path:
        raise DefinitionInvalid(f"{where}: path must start with / and contain no '..', '//', '?', '#' or spaces")
    first = path.split("/")[1] if len(path.split("/")) > 1 else ""
    if not first or "{" in first:
        raise DefinitionInvalid(f"{where}: path must start with a fixed segment (an unscoped path would let a credential reach the whole host)")


def validate_connector(raw: Any) -> Connector:
    """Parse and cross-check one definition. Raises DefinitionInvalid with a readable reason."""
    try:
        c = Connector.model_validate(raw)
    except Exception as e:  # pydantic ValidationError: keep the first problem only
        errs = getattr(e, "errors", None)
        first = errs()[0] if errs else {"loc": (), "msg": str(e)}
        raise DefinitionInvalid(f"{'.'.join(str(x) for x in first['loc'])}: {first['msg']}")

    # auth -------------------------------------------------------------------------------------------------------------------------
    keys = [f.key for f in c.auth.fields]
    if len(set(keys)) != len(keys):
        raise DefinitionInvalid("auth: duplicate field keys")
    need = SCHEME_FIELDS[c.auth.scheme]
    by_key = {f.key: f for f in c.auth.fields}
    for k, secret in need.items():
        if k not in by_key or by_key[k].secret != secret:
            raise DefinitionInvalid(f"auth: scheme '{c.auth.scheme}' needs a field '{k}' with secret={str(secret).lower()}")
    if c.auth.scheme == "header":
        hn = c.auth.header_name or ""
        if not _HEADER_NAME.match(hn) or hn.lower() in _FORBIDDEN_HEADERS - {"authorization"}:
            raise DefinitionInvalid("auth: header_name is required and must be a valid header name")
        if "\r" in c.auth.header_prefix or "\n" in c.auth.header_prefix:
            raise DefinitionInvalid("auth: invalid header_prefix")
    elif c.auth.header_name or c.auth.header_prefix:
        raise DefinitionInvalid("auth: header_name and header_prefix only apply to scheme 'header'")
    config_keys = set()
    for f in c.auth.fields:
        if f.secret:
            if f.pattern:
                raise DefinitionInvalid(f"auth.{f.key}: secret fields cannot have a pattern (it would be echoed in errors)")
            continue
        if not f.pattern:
            raise DefinitionInvalid(f"auth.{f.key}: non-secret fields need a pattern")
        _regex(f.pattern, f"auth.{f.key}")
        config_keys.add(f.key)

    # hosts: placeholders must be config fields whose pattern cannot add dots, slashes, colons or '@' --------------------------
    host_fields = set()
    for h in c.hosts:
        for p in placeholders(h):
            if p not in config_keys:
                raise DefinitionInvalid(f"hosts: placeholder {{{p}}} is not a non-secret auth field")
            host_fields.add(p)
    for p in host_fields:
        rx = re.compile(by_key[p].pattern)
        for bad in ("a.b", "a/b", "a:b", "a@b", "a b", "a\nb", "a#b", "a?b", "a\\b", ""):
            if rx.fullmatch(bad):
                raise DefinitionInvalid(f"auth.{p}: used in a host, so its pattern must not allow {bad!r}")

    # headers ------------------------------------------------------------------------------------------------------------------------
    for k, v in c.headers.items():
        if not _HEADER_NAME.match(k) or k.lower() in _FORBIDDEN_HEADERS or "\r" in v or "\n" in v or placeholders(v):
            raise DefinitionInvalid(f"headers: invalid static header {k!r}")

    # test + actions -----------------------------------------------------------------------------------------------------------
    if c.reply is not None:
        for path in (c.reply.ok, c.reply.error):
            if not _OUT_PATH.match(path):
                raise DefinitionInvalid(f"reply: {path!r} is not a valid path")
        if any(not re.fullmatch(r"[a-z][a-z0-9_]{1,60}", x) for x in c.reply.retry_codes):
            raise DefinitionInvalid("reply: retry_codes must be lowercase words")
    _static_prefix_ok(c.test.path, "test.path")
    for p in placeholders(c.test.path):
        if p not in config_keys:
            raise DefinitionInvalid(f"test.path: placeholder {{{p}}} must be a non-secret auth field")
    seen = set()
    for a in c.actions:
        where = f"action '{a.id}'"
        if a.id in seen:
            raise DefinitionInvalid(f"{where}: duplicate id")
        seen.add(a.id)
        _static_prefix_ok(a.path, f"{where} path")
        ikeys = [i.key for i in a.inputs]
        if len(set(ikeys)) != len(ikeys):
            raise DefinitionInvalid(f"{where}: duplicate input keys")
        if set(ikeys) & config_keys:
            raise DefinitionInvalid(f"{where}: input keys must not reuse auth field keys")
        known = set(ikeys) | config_keys
        for text in [a.path, *a.query.values(), *_walk_strings(a.body)]:
            for p in placeholders(text):
                if p not in known:
                    raise DefinitionInvalid(f"{where}: placeholder {{{p}}} is neither an input nor a non-secret auth field")
        for p in placeholders(a.path):
            inp = next((i for i in a.inputs if i.key == p), None)
            if inp is not None and not inp.required:
                raise DefinitionInvalid(f"{where}: input '{p}' is used in the path, so it must be required")
        for i in a.inputs:
            iw = f"{where} input '{i.key}'"
            if i.multiline and (i.type != "string" or any(i.key in placeholders(t) for t in [a.path, *a.query.values()])):
                raise DefinitionInvalid(f"{iw}: multiline is only for string inputs used in the body")
            if i.type == "string" and not i.pattern:
                raise DefinitionInvalid(f"{iw}: string inputs need a pattern")
            if i.pattern:
                _regex(i.pattern, iw)
            if i.type == "select" and not i.options:
                raise DefinitionInvalid(f"{iw}: select inputs need options")
            if i.type == "integer" and (i.minimum is None or i.maximum is None):
                raise DefinitionInvalid(f"{iw}: integer inputs need minimum and maximum")
            if i.type != "select" and i.options:
                raise DefinitionInvalid(f"{iw}: options only apply to select inputs")
            if i.default is not None and i.required:
                raise DefinitionInvalid(f"{iw}: a required input cannot have a default")
        okeys = [o.key for o in a.outputs]
        if len(set(okeys)) != len(okeys) or {"status_code", "ok"} & set(okeys):
            raise DefinitionInvalid(f"{where}: duplicate or reserved output keys (status_code and ok are always provided)")
        for o in a.outputs:
            if not _OUT_PATH.match(o.from_):
                raise DefinitionInvalid(f"{where} output '{o.key}': 'from' must look like $.a.b, $.a[0].b or $.items[*].name")
        if a.read_only and (a.body is not None):
            raise DefinitionInvalid(f"{where}: GET actions cannot have a body")
        if a.read_only and a.idempotent:
            pass  # reads are always safe to retry; the flag is allowed but redundant
        for code in a.body_errors:
            if not re.fullmatch(r"[a-z][a-z0-9_]{1,60}", code):
                raise DefinitionInvalid(f"{where}: body error codes must be lowercase words like 'channel_not_found'")
        if a.body_errors and c.reply is None:
            raise DefinitionInvalid(f"{where}: body_errors need a connector-level reply block")
        for code in a.errors:
            if not 400 <= code <= 599:
                raise DefinitionInvalid(f"{where}: error codes must be 4xx or 5xx")
    # secret field values are never echoed back: no output may be named like a secret field
    for a in c.actions:
        if {o.key for o in a.outputs} & {f.key for f in c.auth.fields if f.secret}:
            raise DefinitionInvalid(f"action '{a.id}': an output is named like a secret field")
    return c
