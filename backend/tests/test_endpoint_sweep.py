"""Call every /api/v1 operation in the OpenAPI document and check the reply is a SCIM shape and never a 5xx.

Two passes over the same operation list:
* anonymous: every admin operation answers 401 or 403, and every reply is a SCIM shape (public endpoints such as sign-in may answer 2xx or 4xx);
* super admin: every operation, with a bogus id in each path parameter and an empty JSON body, answers without a server error,
  and whatever comes back is a SCIM Error (>= 400), a ListResponse (a list), or a resource with `schemas` and `meta`.
"""

import json

from backend.app.scim.errors import ERROR_SCHEMA
from backend.app.scim.envelope import LIST_URN
from tests.conftest import Api, app, make_user

SKIP_PREFIXES = ("/api/v1/logout",)   # ends the session; the sweep logs in again whenever it is lost
METHODS = ("get", "post", "put", "patch", "delete")
PUBLIC_ADMIN = {"/api/v1/admin/bootstrap"}   # first-run setup, open until the first administrator exists


def operations():
    spec = app.openapi()
    out = []
    for path, item in spec["paths"].items():
        if not path.startswith("/api/v1/"):
            continue
        for method in METHODS:
            op = item.get(method)
            if not op:
                continue
            params = [*item.get("parameters", []), *op.get("parameters", [])]
            body = op.get("requestBody", {}).get("content", {})
            out.append((method, path, params, "application/json" in body))
    return out


def fill(path, params):
    for p in params:
        if p.get("in") == "path":
            kind = (p.get("schema") or {}).get("type")
            path = path.replace("{" + p["name"] + "}", "999999" if kind == "integer" else "does-not-exist")
    return path


def send(api, method, path, has_json):
    kw = {"headers": api._h(csrf=method != "get")}
    if has_json and method in ("post", "put", "patch"):
        kw["json"] = {}
    return api.c.request(method.upper(), path, **kw)


def shape_problem(r):
    """None when the reply is acceptable, else why not."""
    if r.status_code >= 500:
        return f"server error {r.status_code}"
    if r.status_code == 204 or not r.content:
        return None
    if not r.headers.get("content-type", "").startswith("application/json"):
        return None   # files, HTML, plain text: out of scope for the JSON shapes
    try:
        body = r.json()
    except ValueError:
        return "invalid JSON"
    if r.status_code >= 400:
        if not isinstance(body, dict) or ERROR_SCHEMA not in body.get("schemas", []):
            return f"error is not a SCIM Error: {json.dumps(body)[:120]}"
        if body.get("status") != str(r.status_code) or not isinstance(body.get("detail"), str):
            return f"SCIM Error status/detail wrong: {json.dumps(body)[:120]}"
        return None
    if isinstance(body, dict):
        if isinstance(body.get("Resources"), list):
            if LIST_URN not in body.get("schemas", []):
                return "list lacks the ListResponse schema"
        elif body.get("id") is not None and "schemas" not in body:
            return "resource lacks schemas/meta"
    return None


def test_every_operation_is_closed_to_anonymous_callers(db):
    ops = operations()
    assert len(ops) > 150   # the sweep really covers the API
    bad = []
    anon = Api()
    for method, path, params, has_json in ops:
        if path.startswith(SKIP_PREFIXES):
            continue
        r = send(anon, method, fill(path, params), has_json)
        why = shape_problem(r)
        if path.startswith("/api/v1/admin/") and path not in PUBLIC_ADMIN and r.status_code not in (401, 403):
            why = why or f"admin endpoint answered {r.status_code} to an anonymous caller"
        if why:
            bad.append(f"{method.upper()} {path} -> {r.status_code}: {why}")
    assert not bad, "\n".join(bad)


def test_every_operation_answers_in_scim_shapes_as_a_super_admin(db):
    make_user(db, "sweep@example.com", super_admin=True)
    api = Api()
    assert api.login("sweep@example.com").status_code == 200
    ops = operations()
    bad, seen = [], 0
    for method, path, params, has_json in ops:
        if path.startswith(SKIP_PREFIXES):
            continue
        r = send(api, method, fill(path, params), has_json)
        if r.status_code == 401:   # an earlier call ended the session (sign out everywhere, password change…)
            api = Api()
            assert api.login("sweep@example.com").status_code == 200
            r = send(api, method, fill(path, params), has_json)
        seen += 1
        why = shape_problem(r)
        if why:
            bad.append(f"{method.upper()} {path} -> {r.status_code}: {why}")
    assert seen > 150
    assert not bad, "\n".join(bad)
