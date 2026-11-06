"""Structured conditions for trigger filters and `condition` steps (ADR 008; same philosophy as groups/rules.py)."""

from typing import Any, Callable, Dict, List, Optional

from backend.app.recipes import templates as tpl

OPERATORS = (
    "equals", "not_equals", "contains", "starts_with", "ends_with", "is_set", "is_not_set", "greater_than", "less_than",
)
MAX_CONDITIONS = 10


def validate(match: str, conditions: Any) -> List[Dict[str, str]]:
    if match not in ("all", "any"):
        raise tpl.TemplateError("match must be 'all' or 'any'")
    if not isinstance(conditions, list) or not conditions:
        raise tpl.TemplateError("a condition needs at least one comparison")
    if len(conditions) > MAX_CONDITIONS:
        raise tpl.TemplateError(f"at most {MAX_CONDITIONS} comparisons")
    out = []
    for c in conditions:
        if not isinstance(c, dict) or set(c) - {"left", "operator", "value"}:
            raise tpl.TemplateError("each comparison needs left, operator and value only")
        left, op, value = c.get("left"), c.get("operator"), c.get("value", "")
        if not isinstance(left, str):
            raise tpl.TemplateError("comparison 'left' must be a datapill path")
        tpl.check_path(left.strip())
        if op not in OPERATORS:
            raise tpl.TemplateError(f"unknown operator '{op}'")
        if op in ("is_set", "is_not_set"):
            value = ""
        else:
            if not isinstance(value, str) or len(value) > 200:
                raise tpl.TemplateError("comparison value must be text of up to 200 characters")
            tpl.pills_in(value)
        out.append({"left": left.strip(), "operator": op, "value": value})
    return out


def _num(s: str) -> Optional[float]:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _one(c: Dict[str, str], ctx: dict, check: Optional[Callable[[str], None]]) -> bool:
    if check:
        check(c["left"])
    try:
        raw = tpl.resolve_path(ctx, c["left"])
    except tpl.TemplateError:
        raw = None  # a missing datapill counts as "not set"
    have = None if raw is None or raw == "" else tpl.to_text(raw)
    op = c["operator"]
    if op == "is_set":
        return have is not None
    if op == "is_not_set":
        return have is None
    want = tpl.to_text(tpl.render(c["value"], ctx, check))
    if op == "not_equals":
        return have is None or have.lower() != want.lower()
    if have is None:
        return False
    h, w = have.lower(), want.lower()
    if op == "equals":
        return h == w
    if op == "contains":
        return w in h
    if op == "starts_with":
        return h.startswith(w)
    if op == "ends_with":
        return h.endswith(w)
    a, b = _num(have), _num(want)
    if a is None or b is None:
        return False
    return a > b if op == "greater_than" else a < b


def evaluate(match: str, conditions: List[Dict[str, str]], ctx: dict, check: Optional[Callable[[str], None]] = None) -> bool:
    results = (_one(c, ctx, check) for c in conditions)
    return all(results) if match == "all" else any(results)
