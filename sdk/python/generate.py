#!/usr/bin/env python3
"""Generate ifora/_generated.py from the API's OpenAPI document, so the SDK covers every endpoint.

    python generate.py --spec https://api.ifora.app/openapi.json [--insecure]   # write ifora/_generated.py
    python generate.py --spec openapi.json --check                              # fail if the file is out of date

Each API section (the OpenAPI tag) becomes a namespace on the client: `client.users.list()`, `client.groups.get(7)`.
Path parameters are positional, query parameters are keyword-only (snake_case), and a JSON request body is `body=`.
"""

import argparse
import json
import keyword
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Tuple

import httpx

OUT = Path(__file__).parent / "ifora" / "_generated.py"
METHODS = ("get", "post", "put", "patch", "delete")
RESERVED = {"login", "request", "paginate", "close", "base_url", "token", "csrf_token"}   # Transport attributes
SKIP_PREFIX = ("api", "v1", "admin")
PY_TYPES = {"integer": "int", "string": "str", "boolean": "bool", "number": "float", "array": "List[Any]", "object": "Dict[str, Any]"}


def snake(name: str) -> str:
    s = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", name)
    s = re.sub(r"[^0-9a-zA-Z]+", "_", s).strip("_").lower()
    if not s or s[0].isdigit():
        s = "_" + s
    return s + "_" if keyword.iskeyword(s) else s


def load(spec: str, insecure: bool) -> dict:
    if re.match(r"https?://", spec):
        return httpx.get(spec, verify=not insecure, timeout=30).raise_for_status().json()
    return json.loads(Path(spec).read_text())


def deref(spec: dict, node: Any) -> Any:
    seen = 0
    while isinstance(node, dict) and "$ref" in node and seen < 8:
        cur = spec
        for part in node["$ref"].lstrip("#/").split("/"):
            cur = cur[part]
        node, seen = cur, seen + 1
    return node


def py_type(spec: dict, schema: Any) -> str:
    s = deref(spec, schema) or {}
    if "anyOf" in s or "oneOf" in s:
        alts = [a for a in (s.get("anyOf") or s.get("oneOf")) if (a or {}).get("type") != "null"]
        return py_type(spec, alts[0]) if len(alts) == 1 else "Any"
    return PY_TYPES.get(s.get("type"), "Any")


def segments(path: str) -> List[str]:
    segs = [s for s in path.strip("/").split("/") if s]
    while segs and segs[0] in SKIP_PREFIX:
        segs.pop(0)
    return segs


def namespace_of(path: str, op: dict) -> str:
    tag = (op.get("tags") or [None])[0]
    if tag:
        name = snake(tag)
    else:
        segs = segments(path)
        name = snake(segs[0].lstrip(".")) if segs else "other"
    return name + "_" if name in RESERVED else name


def base_name(method: str, path: str, home: str) -> Tuple[str, List[str]]:
    """`home` is the section's main collection (its most common first path segment): its routes are `list/get/create/update/delete`;
    a route outside it keeps its whole path in the name (`get_stats`, `oauth_token`)."""
    segs = segments(path)
    params = [s[1:-1] for s in segs if s.startswith("{")]
    rest = segs[1:] if segs and segs[0] == home else segs
    tail = [s for s in rest if not s.startswith("{")]
    if not tail:
        item = bool(rest)
        verbs = {"get": "get" if item else "list", "post": "create", "put": "replace", "patch": "update", "delete": "delete"}
        return verbs[method], params
    name = "_".join(snake(t) for t in tail)
    if method == "post":
        return name, params
    prefix = {"get": "get", "put": "set", "patch": "update", "delete": "delete"}[method]
    return f"{prefix}_{name}", params


def doc(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')


def body_fields(spec: dict, schema: Any) -> List[str]:
    s = deref(spec, schema) or {}
    props, req = s.get("properties") or {}, set(s.get("required") or [])
    return [f"{k} ({py_type(spec, v)}{', required' if k in req else ''})" for k, v in props.items()]


def build(spec: dict) -> Tuple[str, int]:
    namespaces: Dict[str, List[Tuple[str, str, str, dict]]] = {}
    for path in sorted(spec["paths"]):
        item = spec["paths"][path]
        for method in METHODS:
            op = item.get(method)
            if op:
                namespaces.setdefault(namespace_of(path, op), []).append((method, path, "", {**op, "_item_params": item.get("parameters", [])}))

    lines: List[str] = [
        '"""Generated from the IFora OpenAPI document by generate.py. Do not edit; run `python generate.py --spec …` instead."""',
        "",
        "from typing import Any, Dict, List, Mapping, Optional",
        "",
        "from ._client import Transport, path_arg",
        "",
    ]
    manifest: List[str] = []
    total = 0
    class_names: List[Tuple[str, str]] = []
    for ns in sorted(namespaces):
        cls = "_" + "".join(p.capitalize() for p in ns.strip("_").split("_"))
        class_names.append((ns, cls))
        lines += [f"class {cls}:", f'    """Endpoints in the `{ns}` section."""', "", "    def __init__(self, t: Transport):", "        self._t = t", ""]
        used: set = set()
        firsts = Counter((segments(p) or [""])[0] for _, p, _, _ in namespaces[ns])
        home = sorted(firsts, key=lambda s: (-firsts[s], s))[0]
        for method, path, _, op in sorted(namespaces[ns], key=lambda x: (x[1], x[0])):
            name, pnames = base_name(method, path, home)
            if name in used or name in RESERVED:
                scope = "admin" if path.startswith("/api/v1/admin/") else "me" if path.startswith("/api/v1/me") else ""
                for alt in (f"{name}_by_{'_'.join(snake(p) for p in pnames)}" if pnames else "", f"{name}_{scope}" if scope else "", f"{name}_{method}"):
                    if alt and alt not in used and alt not in RESERVED:
                        name = alt
                        break
            n = 2
            while name in used:
                name, n = f"{name.rstrip('0123456789_')}_{n}", n + 1
            used.add(name)

            raw_params = [*op["_item_params"], *op.get("parameters", [])]
            params = [deref(spec, p) for p in raw_params]
            path_params = [p for p in params if p.get("in") == "path"]
            query_params = [p for p in params if p.get("in") == "query"]
            content = (op.get("requestBody") or {}).get("content", {})
            json_body = "application/json" in content
            form_body = "application/x-www-form-urlencoded" in content
            body_required = bool((op.get("requestBody") or {}).get("required"))

            taken = {"self", "body", "form"}
            sig: List[str] = ["self"]
            path_map: Dict[str, str] = {}
            for p in path_params:
                py = snake(p["name"])
                while py in taken:
                    py += "_"
                taken.add(py)
                path_map[p["name"]] = py
                sig.append(f"{py}: {py_type(spec, p.get('schema'))}")
            if json_body:
                sig.append("body: Mapping[str, Any]" if body_required else "body: Optional[Mapping[str, Any]] = None")
            if form_body:
                sig.append("form: Mapping[str, Any]" if body_required else "form: Optional[Mapping[str, Any]] = None")
            query_map: Dict[str, str] = {}
            q_sig: List[str] = []
            for p in query_params:
                py = snake(p["name"])
                while py in taken:
                    py += "_"
                taken.add(py)
                query_map[p["name"]] = py
                t = py_type(spec, p.get("schema"))
                q_sig.append(f"{py}: {t}" if p.get("required") else f"{py}: Optional[{t}] = None")
            # Protocol endpoints (OAuth, SAML, discovery) read the raw request, so the document declares no parameters: let callers pass them.
            protocol = not path.startswith("/api/v1/")
            if protocol and method in ("post", "put", "patch") and not form_body:
                sig.append("form: Optional[Mapping[str, Any]] = None")
                form_body = True
            extra_query = protocol and not query_params
            if q_sig or extra_query:
                sig += ["*", *q_sig]
            if extra_query:
                sig.append("query: Optional[Mapping[str, Any]] = None")

            url = path
            for orig, py in path_map.items():
                url = url.replace("{" + orig + "}", "{" + py + "}")
            has_path = bool(path_map)
            url_expr = ('f"' + re.sub(r"\{(\w+)\}", lambda m: "{path_arg(" + m.group(1) + ")}", url) + '"') if has_path else json.dumps(url)

            summary = (op.get("summary") or "").strip()
            desc = (op.get("description") or "").strip().split("\n\n")[0].replace("\n", " ")
            fields = body_fields(spec, content["application/json"].get("schema")) if json_body else []
            d = [f"{method.upper()} {path}"]
            if summary and summary != desc:
                d.append(summary)
            if desc:
                d.append(desc[:400])
            if fields:
                d.append("Body fields: " + ", ".join(fields[:40]) + (", …" if len(fields) > 40 else ""))
            if not path.startswith("/api/v1/admin/"):
                d.append("Needs a session: call client.login() first." if path.startswith("/api/v1/") else "Protocol endpoint (not under /api/v1).")

            lines.append(f"    def {name}({', '.join(sig)}) -> Any:")
            lines.append('        """' + doc("\n\n        ".join(d)) + '"""')
            call = [f'"{method.upper()}"', url_expr]
            if query_map:
                call.append("query={" + ", ".join(f'"{o}": {py}' for o, py in query_map.items()) + "}")
            elif extra_query:
                call.append("query=query")
            if json_body:
                call.append("json=body")
            if form_body:
                call.append("form=form")
            lines.append(f"        return self._t.request({', '.join(call)})")
            lines.append("")
            manifest.append(f'    ("{method.upper()}", {json.dumps(path)}, "{ns}.{name}"),')
            total += 1

    lines += ["", "class Namespaces:", '    """One attribute per API section. Mixed into Client, which supplies the transport (self)."""', "", "    def _attach(self) -> None:"]
    for ns, cls in class_names:
        lines.append(f"        self.{ns} = {cls}(self)  # type: ignore[arg-type]")
    lines += ["", "", "# Every operation in the OpenAPI document: (HTTP method, path, 'section.method').", "OPERATIONS = ["]
    lines += manifest + ["]", ""]
    return "\n".join(lines), total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True, help="URL or file of the OpenAPI document")
    ap.add_argument("--insecure", action="store_true", help="do not verify TLS (a local development CA)")
    ap.add_argument("--check", action="store_true", help="exit 1 if the generated file differs")
    a = ap.parse_args()
    text, n = build(load(a.spec, a.insecure))
    if a.check:
        if OUT.read_text() != text:
            print("ifora/_generated.py is out of date; run generate.py", file=sys.stderr)
            return 1
        print(f"up to date ({n} operations)")
        return 0
    OUT.write_text(text)
    print(f"wrote {OUT} ({n} operations)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
