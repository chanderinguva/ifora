"""Datapill templating: ``{{trigger.user.email}}`` and formulas ``{{= upper(trigger.user.email) }}`` (see formula.py).

A pill is a dotted path into plain JSON data (dicts and lists) below an allow-listed root. There is no attribute
access on Python objects, so names like ``__class__`` cannot resolve to anything (and are rejected outright).
A formula is a pure expression over pills and a fixed function library; every pill it reads goes through the same
path check and taint check as a plain pill.
"""

import json
import re
from typing import Any, Callable, Iterable, List, Optional, Tuple

from backend.app.recipes import formula

ROOTS = ("trigger", "steps", "recipe", "job", "error", "loop", "vars")
MAX_PATH_SEGMENTS = 10
MAX_RENDERED = 10_000
MAX_FORMULAS = 10
_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
PILL = re.compile(r"\{\{\s*([A-Za-z0-9_.\-]+)\s*\}\}")


class TemplateError(ValueError):
    """Bad template or unresolvable datapill. The message is safe to show to admins."""


def check_path(path: str) -> List[str]:
    segs = path.split(".")
    if len(segs) < 2 or segs[0] not in ROOTS:
        raise TemplateError(f"datapill '{path}' must start with one of: {', '.join(ROOTS)}")
    if len(segs) > MAX_PATH_SEGMENTS:
        raise TemplateError(f"datapill '{path}' is too deep")
    for s in segs:
        if not _SEGMENT.match(s):
            raise TemplateError(f"datapill '{path}' contains an invalid name")
    return segs


def split(template: str) -> List[Tuple[str, Any]]:
    """Cut a template into ('text', str), ('pill', path) and ('formula', ast) parts."""
    if not isinstance(template, str):
        raise TemplateError("template must be text")
    out: List[Tuple[str, Any]] = []
    i, n = 0, len(template)
    while i < n:
        j = template.find("{{", i)
        if j < 0:
            out.append(("text", template[i:]))
            break
        if j > i:
            out.append(("text", template[i:j]))
        k = j + 2
        while k < n and template[k] in " \t":
            k += 1
        if k < n and template[k] == "=":   # a formula: scan to the closing }} outside any quoted text
            q, e = None, k + 1
            while e < n:
                c = template[e]
                if q:
                    if c == "\\":
                        e += 1
                    elif c == q:
                        q = None
                elif c in "'\"":
                    q = c
                elif template.startswith("}}", e):
                    break
                e += 1
            if e >= n:
                raise TemplateError("a formula is missing its closing }}")
            try:
                out.append(("formula", formula.parse(template[k + 1:e])))
            except formula.FormulaError as err:
                raise TemplateError(f"formula: {err}")
            i = e + 2
            continue
        m = PILL.match(template, j)
        if m:
            out.append(("pill", m.group(1)))
            i = m.end()
        else:
            out.append(("text", "{{"))
            i = j + 2
    return out


def pills_in(template: str) -> List[str]:
    """All paths used by a template (including those read by its formulas); raises on anything malformed."""
    paths: List[str] = []
    formulas = 0
    for kind, val in split(template):
        if kind == "text":
            if "{{" in val or "}}" in val:
                raise TemplateError("only {{datapill.path}} references and {{= formulas }} are allowed")
        elif kind == "pill":
            paths.append(val)
        else:
            formulas += 1
            if formulas > MAX_FORMULAS:
                raise TemplateError(f"at most {MAX_FORMULAS} formulas in one field")
            paths.extend(formula.paths(val))
    for p in paths:
        check_path(p)
    return paths


def resolve_path(ctx: dict, path: str) -> Any:
    segs = check_path(path)
    cur: Any = ctx
    for s in segs:
        if isinstance(cur, dict):
            if s not in cur:
                raise TemplateError(f"datapill '{path}' has no value")
            cur = cur[s]
        elif isinstance(cur, list) and s.isdigit() and int(s) < len(cur):
            cur = cur[int(s)]
        else:
            raise TemplateError(f"datapill '{path}' has no value")
    return cur


def to_text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (dict, list)):
        return json.dumps(v, separators=(",", ":"), sort_keys=True)
    return str(v)


def _lenient(ctx: dict, path: str) -> Any:
    try:
        return resolve_path(ctx, path)
    except TemplateError:
        return None   # inside a formula a missing value is "nothing" (use coalesce/is_blank); save-time checks catch bad paths


def render(template: str, ctx: dict, check: Optional[Callable[[str], None]] = None) -> Any:
    """Substitute pills and evaluate formulas. A template that is exactly one pill or formula returns the raw JSON value."""
    pills_in(template)
    parts = split(template)

    def value(kind: str, val: Any) -> Any:
        if kind == "pill":
            if check:
                check(val)
            return resolve_path(ctx, val)

        def read(path: str) -> Any:
            check_path(path)
            if check:
                check(path)
            return _lenient(ctx, path)

        try:
            return formula.evaluate(val, read)
        except formula.FormulaError as e:
            raise TemplateError(f"formula: {e}")

    real = [p for p in parts if not (p[0] == "text" and not p[1].strip())]
    if len(real) == 1 and real[0][0] in ("pill", "formula"):
        return value(*real[0])
    out = "".join(p[1] if p[0] == "text" else to_text(value(*p)) for p in parts)
    if len(out) > MAX_RENDERED:
        raise TemplateError("rendered text is too long")
    return out


def render_value(value: Any, ctx: dict, check: Optional[Callable[[str], None]] = None) -> Any:
    """Render every string inside a JSON-like structure."""
    if isinstance(value, str):
        return render(value, ctx, check)
    if isinstance(value, dict):
        return {k: render_value(v, ctx, check) for k, v in value.items()}
    if isinstance(value, list):
        return [render_value(v, ctx, check) for v in value]
    return value


def all_pills(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield from pills_in(value)
    elif isinstance(value, dict):
        for v in value.values():
            yield from all_pills(v)
    elif isinstance(value, list):
        for v in value:
            yield from all_pills(v)
