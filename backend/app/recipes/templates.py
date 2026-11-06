"""Datapill templating: ``{{trigger.user.email}}``. No expressions, no filters, no code.

A pill is a dotted path into plain JSON data (dicts and lists) below an allow-listed root. There is no attribute
access on Python objects, so names like ``__class__`` cannot resolve to anything (and are rejected outright).
"""

import json
import re
from typing import Any, Callable, Iterable, List, Optional

ROOTS = ("trigger", "steps", "recipe", "job")
MAX_PATH_SEGMENTS = 10
MAX_RENDERED = 10_000
_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
PILL = re.compile(r"\{\{\s*([A-Za-z0-9_.\-]+)\s*\}\}")
_WHOLE = re.compile(r"^\s*\{\{\s*([A-Za-z0-9_.\-]+)\s*\}\}\s*$")


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


def pills_in(template: str) -> List[str]:
    """All paths used by a template; raises if the string contains anything that looks like an expression."""
    if not isinstance(template, str):
        raise TemplateError("template must be text")
    paths = PILL.findall(template)
    rest = PILL.sub("", template)
    if "{{" in rest or "}}" in rest:
        raise TemplateError("only plain {{datapill.path}} references are allowed (no expressions)")
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


def render(template: str, ctx: dict, check: Optional[Callable[[str], None]] = None) -> Any:
    """Substitute pills. A string that is exactly one pill returns the raw JSON value (ids stay integers)."""
    pills_in(template)
    whole = _WHOLE.match(template)
    if whole:
        if check:
            check(whole.group(1))
        return resolve_path(ctx, whole.group(1))

    def sub(m):
        if check:
            check(m.group(1))
        return to_text(resolve_path(ctx, m.group(1)))

    out = PILL.sub(sub, template)
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
