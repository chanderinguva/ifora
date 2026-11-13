"""Generic HTTPS connections. Secret values never belong to a recipe definition.

Bindings inject encrypted fields into headers/query/JSON/form bodies at execution
time. OAuth token URLs are explicitly configured and pass the same SSRF controls.
"""
import base64
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from backend.app.recipes import crypto
from backend.app.recipes.http_client import EgressBlocked, HttpFailure, ResponseTooLarge, EgressPolicy, safe_request, validate_url

KEY = r"^[a-z][a-z0-9_]{0,39}$"
FORBIDDEN = {"host", "content-length", "transfer-encoding", "connection", "upgrade", "te", "trailer", "expect", "idempotency-key"}
AUTH_TYPES = ("none", "basic", "bearer", "api_key", "custom", "oauth2_client_credentials", "oauth2_authorization_code")


class AuthError(ValueError):
    """Safe message: never include a remote body or credential."""


class Binding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    secret_key: str = Field(pattern=KEY)
    location: Literal["header", "query", "json", "form"]
    name: str = Field(min_length=1, max_length=100)


class HttpConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    auth_type: Literal["none", "basic", "bearer", "api_key", "custom", "oauth2_client_credentials", "oauth2_authorization_code"] = "none"
    bindings: list[Binding] = Field(default_factory=list, max_length=20)
    client_id: str = Field("", max_length=255)
    token_url: str = Field("", max_length=2000)
    authorization_url: str = Field("", max_length=2000)
    scope: str = Field("", max_length=1000)
    client_auth: Literal["basic", "post", "none"] = "basic"


def config(raw):
    try:
        c = HttpConfig.model_validate(raw or {})
    except ValidationError:
        raise AuthError("Invalid HTTP authentication settings") from None
    if c.auth_type in ("api_key", "custom") and not c.bindings:
        raise AuthError("Add at least one secret field binding")
    if c.auth_type not in ("api_key", "custom") and c.bindings:
        raise AuthError("Secret bindings apply to API key or custom authentication")
    seen = set()
    for b in c.bindings:
        if any(ord(x) < 32 or ord(x) == 127 for x in b.name):
            raise AuthError("Invalid secret field name")
        if b.location == "header" and (not re.fullmatch(r"[A-Za-z0-9-]+", b.name) or b.name.lower() in FORBIDDEN):
            raise AuthError("Invalid secret header")
        identity = (b.location, b.name.lower() if b.location == "header" else b.name)
        if identity in seen:
            raise AuthError("Duplicate secret field destination")
        seen.add(identity)
    if len({b.location for b in c.bindings} & {"json", "form"}) > 1:
        raise AuthError("Choose JSON or form body authentication, not both")
    if c.auth_type.startswith("oauth2"):
        if c.auth_type == "oauth2_client_credentials" and c.client_auth == "none":
            raise AuthError("Client credentials requires a confidential client")
        if not c.client_id:
            raise AuthError("Client ID is required")
        endpoint(c.token_url)
        if c.auth_type == "oauth2_authorization_code":
            endpoint(c.authorization_url)
    return c


def endpoint(url):
    try:
        u = urlsplit(url)
        if u.scheme != "https" or not u.hostname or u.username or u.password or u.fragment or u.query:
            raise ValueError()
        validate_url(url, EgressPolicy.from_settings())
    except (ValueError, EgressBlocked):
        raise AuthError("OAuth endpoints must be fixed HTTPS URLs without query strings or credentials") from None


def required_keys(c):
    if c.auth_type == "basic":
        return {"username", "password"}
    if c.auth_type == "bearer":
        return {"token"}
    if c.auth_type.startswith("oauth2"):
        return {"client_secret"} if c.client_auth != "none" else set()
    return {b.secret_key for b in c.bindings}


def validate_request_fields(cfg):
    from backend.app.recipes.redact import _SENSITIVE_KEY
    for name, value in (cfg.get("headers") or {}).items():
        if _SENSITIVE_KEY.search(name) and value:
            raise AuthError("Store credential headers in the connection, not in the recipe")
    for name, value in parse_qsl(urlsplit(cfg.get("url", "")).query):
        if _SENSITIVE_KEY.search(name) and value:
            raise AuthError("Store credential query parameters in the connection")
    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if _SENSITIVE_KEY.search(key) and value:
                    raise AuthError("Store credential body fields in the connection")
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    try:
        walk(json.loads(cfg.get("body") or "{}"))
    except json.JSONDecodeError:
        for key, value in parse_qsl(cfg.get("body") or ""):
            if _SENSITIVE_KEY.search(key) and value:
                raise AuthError("Store credential body fields in the connection")


def validate_secrets(c, supplied, existing=None):
    keys = required_keys(c)
    if not isinstance(supplied, dict) or set(supplied) - keys:
        raise AuthError("Only declared credential fields may be supplied")
    # Retain OAuth tokens only when updating an unchanged configuration.
    result = dict(existing or {})
    for key, value in supplied.items():
        if not isinstance(value, str) or not value or len(value) > 16000 or any(ord(x) < 32 or ord(x) == 127 for x in value):
            raise AuthError("Credential fields must be nonempty text without control characters")
        result[key] = value
    if keys - set(result):
        raise AuthError("Enter all required credential fields")
    return result


def values(conn):
    try:
        v = json.loads(crypto.decrypt(conn.secret_enc))
        if not isinstance(v, dict):
            raise ValueError()
        return v
    except (ValueError, TypeError):
        raise AuthError("Saved credentials are invalid; reauthorize the connection") from None


def token_request(c, sec, form, *, policy=None, resolver=None, transport=None):
    headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
    if c.client_auth == "basic":
        credential = urlencode({"x": c.client_id})[2:] + ":" + urlencode({"x": sec.get("client_secret", "")})[2:]
        headers["Authorization"] = "Basic " + base64.b64encode(credential.encode()).decode()
    else:
        form["client_id"] = c.client_id
        if c.client_auth == "post":
            form["client_secret"] = sec.get("client_secret", "")
    try:
        res = safe_request("POST", c.token_url, headers, urlencode(form).encode(),
                           policy=policy or EgressPolicy.from_settings(), resolver=resolver, transport=transport)
        if res.status != 200:
            raise AuthError("OAuth token exchange was refused; reauthorize the connection")
        data = json.loads(res.body)
        token = data.get("access_token")
        if not isinstance(token, str) or not token or len(token) > 16000 or any(ord(x) < 32 or ord(x) == 127 for x in token):
            raise ValueError()
        if str(data.get("token_type", "")).lower() != "bearer":
            raise ValueError()
        ttl = data.get("expires_in", 300)
        if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or not 1 <= ttl <= 31536000:
            raise ValueError()
        out = {**sec, "access_token": token, "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=ttl)).isoformat()}
        if "refresh_token" in data:
            refresh = data["refresh_token"]
            if not isinstance(refresh, str) or not refresh or len(refresh) > 16000 or any(ord(x) < 32 or ord(x) == 127 for x in refresh):
                raise ValueError()
            out["refresh_token"] = refresh
        scopes = data.get("scope")
        return out, scopes.split() if isinstance(scopes, str) else None
    except (ValueError, TypeError, EgressBlocked, HttpFailure, ResponseTooLarge):
        raise AuthError("OAuth token exchange failed; check the connection settings") from None


def access_token(db, conn, c, *, policy=None, resolver=None, transport=None):
    from backend.app.recipes.models import RecipeConnection
    # Serialize refresh-token rotation across workers/processes. Never cache tokens in job history.
    conn = db.query(RecipeConnection).filter(RecipeConnection.id == conn.id).populate_existing().with_for_update().one()
    if conn.config != c.model_dump():
        raise AuthError("Connection settings changed; retry the action")
    sec = values(conn)
    try:
        if sec.get("access_token") and datetime.fromisoformat(sec["expires_at"]) > datetime.now(timezone.utc) + timedelta(seconds=30):
            return sec["access_token"], list(sec.values())
    except (ValueError, KeyError, TypeError):
        pass
    if c.auth_type == "oauth2_client_credentials":
        form = {"grant_type": "client_credentials"}
        if c.scope:
            form["scope"] = c.scope
    elif sec.get("refresh_token"):
        form = {"grant_type": "refresh_token", "refresh_token": sec["refresh_token"]}
    else:
        raise AuthError("Authorize this connection before running a recipe")
    updated, scopes = token_request(c, sec, form, policy=policy, resolver=resolver, transport=transport)
    conn.secret_enc = crypto.encrypt(json.dumps(updated))
    if scopes is not None:
        conn.granted_scopes, conn.scopes_checked_at = sorted(set(scopes)), datetime.now(timezone.utc)
    db.flush()
    return updated["access_token"], list(updated.values())


def inject(c, sec, url, headers, body):
    """Return final request values and every derived secret to scrub from responses."""
    headers = dict(headers)
    sensitive = list(sec.values())
    def header(name, value):
        # Refuse ambiguous duplicate Authorization/API-key header variants.
        for key in list(headers):
            if key.lower() == name.lower():
                del headers[key]
        headers[name] = value
    if c.auth_type == "basic":
        raw = sec["username"] + ":" + sec["password"]
        if ":" in sec["username"]:
            raise AuthError("Basic authentication username cannot contain a colon")
        encoded = base64.b64encode(raw.encode()).decode()
        sensitive += [encoded, "Basic " + encoded]
        header("Authorization", "Basic " + encoded)
    elif c.auth_type == "bearer":
        header("Authorization", "Bearer " + sec["token"])
    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    json_body, form_body = None, None
    for b in c.bindings:
        if b.secret_key not in sec:
            raise AuthError("A required credential is missing")
        value = sec[b.secret_key]
        sensitive += [value, urlencode({"x": value})[2:]]
        if b.location == "header":
            header(b.name, value)
        elif b.location == "query":
            query = [(k, v) for k, v in query if k != b.name] + [(b.name, value)]
        elif b.location == "json":
            if json_body is None:
                try:
                    json_body = json.loads(body or "{}")
                    if not isinstance(json_body, dict):
                        raise ValueError()
                except (ValueError, TypeError):
                    raise AuthError("Body credentials require a JSON object") from None
            json_body[b.name] = value
        elif b.location == "form":
            if form_body is None:
                form_body = dict(parse_qsl(body or "", keep_blank_values=True))
            form_body[b.name] = value
    if json_body is not None:
        body = json.dumps(json_body)
        header("Content-Type", "application/json")
    if form_body is not None:
        body = urlencode(form_body)
        header("Content-Type", "application/x-www-form-urlencoded")
    url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
    return url, headers, body, sensitive
