"""SCIM resource envelope for the admin and self-service API (RFC 7643 3.1 `schemas` and `meta`, RFC 7644 3.4.2 ListResponse).

Applied centrally to every successful JSON response under /api/v1, so no route can forget it:

* a single resource (a JSON object with an `id`) gets `schemas` and `meta` {resourceType, created, lastModified, location};
* a list reply (the ADR 025 envelope) gets the ListResponse `schemas` URN, and each item in `Resources` gets the same as above.

Purely additive: existing fields (including the integer `id`) are untouched, and a resource that already carries its own
`schemas` or `meta` (the /scim/v2 documents) is left alone. Nested objects are never touched, so definitions that clients send back
(recipes, connectors) stay exactly as they were.
"""

import json
import re
from typing import Any, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

LIST_URN = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
SCHEMA_PREFIX = "urn:ifora:params:scim:schemas:2.0:"
MAX_BYTES = 8 * 1024 * 1024   # larger replies (exports) pass through untouched
CREATED_KEYS = ("created_at", "created")
MODIFIED_KEYS = ("updated_at", "modified_at", "last_modified", "updated")


def resource_type(path_template: str) -> Optional[str]:
    """`/api/v1/admin/api-tokens/{token_id}` -> `ApiToken`. The last literal segment names the collection."""
    segs = [s for s in path_template.split("/") if s and not s.startswith("{")]
    segs = [s for s in segs if s not in ("api", "v1")]
    if not segs:
        return None
    word = segs[-1]
    if word.endswith("ies"):
        word = word[:-3] + "y"
    elif word.endswith("sses"):
        word = word[:-2]
    elif word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    name = "".join(p[:1].upper() + p[1:] for p in re.split(r"[-_]", word) if p)
    return name or None


def _decorate(doc: dict, rtype: str, location: str) -> None:
    if "schemas" in doc or "meta" in doc:
        return
    doc["schemas"] = [SCHEMA_PREFIX + rtype]
    meta: dict = {"resourceType": rtype, "location": location}
    for key in CREATED_KEYS:
        if isinstance(doc.get(key), str):
            meta["created"] = doc[key]
            break
    for key in MODIFIED_KEYS:
        if isinstance(doc.get(key), str):
            meta["lastModified"] = doc[key]
            break
    doc["meta"] = meta


def envelope(body: Any, path_template: str, url: str, is_item_route: bool) -> Any:
    """Return `body` decorated, or unchanged if it is not a resource or a list of resources."""
    if not isinstance(body, dict):
        return body
    rtype = resource_type(path_template)
    if rtype is None:
        return body
    base = url.split("?", 1)[0].rstrip("/")
    if isinstance(body.get("Resources"), list) and "totalResults" in body:
        if "schemas" not in body:
            body = {"schemas": [LIST_URN], **body}
        for item in body["Resources"]:
            if isinstance(item, dict) and item.get("id") is not None:
                _decorate(item, rtype, f"{base}/{item['id']}")
        return body
    if "id" in body and body["id"] is not None:
        _decorate(body, rtype, base if is_item_route else f"{base}/{body['id']}")
    return body


class ScimEnvelopeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if not path.startswith("/api/v1/") or not (200 <= response.status_code < 300) or response.status_code == 204:
            return response
        if not response.headers.get("content-type", "").startswith("application/json"):
            return response
        chunks = []
        size = 0
        async for chunk in response.body_iterator:
            chunks.append(chunk)
            size += len(chunk)
        raw = b"".join(chunks)
        headers = {k: v for k, v in response.headers.items() if k.lower() not in ("content-length", "set-cookie")}
        out = Response(content=raw, status_code=response.status_code, headers=headers, media_type="application/json")
        for k, v in response.headers.raw:   # keep every Set-Cookie
            if k.lower() == b"set-cookie":
                out.raw_headers.append((k, v))
        if size > MAX_BYTES:
            return out
        try:
            body = json.loads(raw)
        except ValueError:
            return out
        route = request.scope.get("route")
        template = getattr(route, "path", None) or path
        is_item = template.rstrip("/").endswith("}")
        new = envelope(body, template, str(request.url), is_item)
        if new is body and not isinstance(body, dict):
            return out
        out.body = json.dumps(new, separators=(",", ":")).encode()
        out.headers["content-length"] = str(len(out.body))
        return out
