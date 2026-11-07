"""POST /Bulk (RFC 7644 3.7): several writes in one request.

Each operation runs through exactly the same handler as its single-resource endpoint (same validation, audit, side
effects) and commits on its own, as RFC 7644 allows; there is no all-or-nothing transaction. `failOnErrors` stops after
that many failures. `bulkId:<id>` references to an earlier POST in the same request are resolved in `data` and in paths;
forward references are not supported and fail that operation. Token scopes are checked per operation, so a Users-only
token cannot reach Groups through Bulk.
"""

import json
import re
from typing import Any, Callable, Dict, List, Optional

from starlette.requests import Request

from backend.app.scim.auth import Ctx, scope_violation
from backend.app.scim.errors import ScimError, invalid_syntax, invalid_value

BULK_REQ = "urn:ietf:params:scim:api:messages:2.0:BulkRequest"
BULK_RESP = "urn:ietf:params:scim:api:messages:2.0:BulkResponse"
MAX_OPERATIONS = 100
_PATH = re.compile(r"^/(Users|Groups)(?:/([^/?#]{1,64}))?$")
_REF = "bulkId:"


def _resolve(value: Any, ids: Dict[str, str]) -> Any:
    if isinstance(value, str) and value.startswith(_REF):
        key = value[len(_REF):]
        if key not in ids:
            raise invalid_value(f"Unresolved reference '{value}' (it must refer to an earlier POST in this request)")
        return ids[key]
    if isinstance(value, list):
        return [_resolve(v, ids) for v in value]
    if isinstance(value, dict):
        return {k: _resolve(v, ids) for k, v in value.items()}
    return value


def _with_if_match(request: Request, version: Optional[str]) -> Request:
    headers = [(k, v) for k, v in request.scope["headers"] if k.lower() != b"if-match"]
    if version:
        headers.append((b"if-match", version.encode()))
    return Request({**request.scope, "headers": headers}, request.receive)


def execute(ctx: Ctx, body: Any, table: Dict[tuple, Callable], max_payload: int) -> Dict[str, Any]:
    """`table[(METHOD, "users"|"groups", has_id)]` -> callable(ctx, request, resource_id, data) -> ScimResponse."""
    if not isinstance(body, dict) or BULK_REQ not in (body.get("schemas") or []):
        raise invalid_syntax("Body must be a BulkRequest")
    ops = body.get("Operations")
    if not isinstance(ops, list) or not ops:
        raise invalid_syntax("Operations must be a non-empty list")
    if len(ops) > MAX_OPERATIONS:
        raise ScimError(413, f"At most {MAX_OPERATIONS} operations per request", "tooMany")
    fail_on = body.get("failOnErrors")
    if fail_on is not None and (isinstance(fail_on, bool) or not isinstance(fail_on, int) or fail_on < 0):
        raise invalid_syntax("failOnErrors must be a non-negative integer")

    ids: Dict[str, str] = {}
    results: List[Dict[str, Any]] = []
    errors = 0
    for op in ops:
        res = _one(ctx, op, ids, table)
        results.append(res)
        if int(res["status"]) >= 400:
            errors += 1
            if fail_on and errors >= fail_on:
                break
    return {"schemas": [BULK_RESP], "Operations": results}


def _one(ctx: Ctx, op: Any, ids: Dict[str, str], table: Dict[tuple, Callable]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    try:
        if not isinstance(op, dict):
            raise invalid_syntax("Each operation must be an object")
        method = str(op.get("method", "")).upper()
        out["method"] = method
        bulk_id = op.get("bulkId")
        if bulk_id is not None:
            if not isinstance(bulk_id, str) or not 0 < len(bulk_id) <= 64:
                raise invalid_value("bulkId must be a string of 1 to 64 characters")
            out["bulkId"] = bulk_id
        path = op.get("path")
        if isinstance(path, str) and _REF in path:
            path = re.sub(r"bulkId:([^/]+)", lambda mo: _resolve(mo.group(0), ids), path)
        m = _PATH.match(path) if isinstance(path, str) else None
        if m is None or method not in ("POST", "PUT", "PATCH", "DELETE"):
            raise invalid_value("Each operation needs a method (POST, PUT, PATCH, DELETE) and a path (/Users, /Users/{id}, /Groups, /Groups/{id})")
        kind, rid = m.group(1).lower(), m.group(2)
        if (method == "POST") == (rid is not None):
            raise invalid_value("POST goes to the collection (/Users); PUT, PATCH and DELETE need a resource id")
        if method == "POST" and not bulk_id:
            raise invalid_value("POST operations need a bulkId")
        denied = scope_violation(ctx.token, method, "/scim/v2" + path)
        if denied:
            raise ScimError(403, denied)
        data = None
        if method != "DELETE":
            if "data" not in op:
                raise invalid_value("data is required")
            data = _resolve(op["data"], ids)
        version = op.get("version")
        request = _with_if_match(ctx.request, version if isinstance(version, str) else None)
        resp = table[(method, kind, rid is not None)](ctx, request, rid, data)
        out["status"] = str(resp.status_code)
        if resp.headers.get("location"):
            out["location"] = resp.headers["location"]
        elif rid:
            out["location"] = f"{ctx.request.base_url}scim/v2{path}".replace("//scim", "/scim")
        if resp.headers.get("etag"):
            out["version"] = resp.headers["etag"]
        if method == "POST" and resp.status_code < 300 and bulk_id:
            try:
                ids[bulk_id] = json.loads(resp.body)["id"]
            except (ValueError, KeyError):
                pass
    except ScimError as e:
        ctx.db.rollback()
        out["status"] = str(e.status)
        out["response"] = e.body()
    except Exception:  # noqa: BLE001 - one bad operation must not leak internals or abort the rest
        ctx.db.rollback()
        out["status"] = "500"
        out["response"] = ScimError(500, "Internal server error").body()
    return out
