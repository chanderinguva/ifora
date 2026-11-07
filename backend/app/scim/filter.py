"""SCIM filter parser (RFC 7644 3.4.2.2): tokenizer + recursive descent, compiled to SQLAlchemy expressions.

No eval and no SQL text: attributes are looked up in a per-resource allow-list that maps to columns, values are
bound parameters. Supported: eq ne co sw ew gt ge lt le pr, and, or, not(...), parentheses and valuePath filters
(`emails[type eq "work"].value co "x"`). gt/ge/lt/le also work on dates (`meta.lastModified`). Anything else is an
invalidFilter error.
"""

import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from datetime import datetime, timezone

from sqlalchemy import and_, false, func, or_, true

from backend.app.scim.errors import ScimError

MAX_LENGTH = 1000
MAX_TOKENS = 60
MAX_DEPTH = 10
COMPARE_OPS = {"eq", "ne", "co", "sw", "ew", "gt", "ge", "lt", "le"}
ORDER_OPS = {"gt", "ge", "lt", "le"}
_WORD = re.compile(r"[A-Za-z0-9_.:$\-]+")


def bad_filter(detail: str) -> ScimError:
    return ScimError(400, detail, "invalidFilter")


@dataclass
class Tok:
    kind: str  # word | str | lp | rp | lb | rb
    value: str


def tokenize(text: str) -> List[Tok]:
    if len(text) > MAX_LENGTH:
        raise bad_filter("Filter is too long")
    toks: List[Tok] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
        elif ch == "(":
            toks.append(Tok("lp", ch)); i += 1
        elif ch == ")":
            toks.append(Tok("rp", ch)); i += 1
        elif ch == "[":
            toks.append(Tok("lb", ch)); i += 1
        elif ch == "]":
            toks.append(Tok("rb", ch)); i += 1
        elif ch == '"':
            i += 1
            buf = []
            while True:
                if i >= n:
                    raise bad_filter("Unterminated string in filter")
                c = text[i]
                if c == "\\":
                    if i + 1 >= n:
                        raise bad_filter("Bad escape in filter")
                    nxt = text[i + 1]
                    buf.append({"n": "\n", "t": "\t", "r": "\r"}.get(nxt, nxt))
                    i += 2
                elif c == '"':
                    i += 1
                    break
                else:
                    buf.append(c)
                    i += 1
            toks.append(Tok("str", "".join(buf)))
        else:
            m = _WORD.match(text, i)
            if not m:
                raise bad_filter("Unexpected character in filter")
            toks.append(Tok("word", m.group(0)))
            i = m.end()
        if len(toks) > MAX_TOKENS:
            raise bad_filter("Filter is too complex")
    return toks


# AST: ("and"|"or", left, right) | ("pr", attr) | ("cmp", attr, op, value)
Node = Tuple[Any, ...]


class _Parser:
    def __init__(self, toks: List[Tok]):
        self.t, self.i = toks, 0

    def peek(self) -> Optional[Tok]:
        return self.t[self.i] if self.i < len(self.t) else None

    def next(self) -> Tok:
        tok = self.peek()
        if tok is None:
            raise bad_filter("Unexpected end of filter")
        self.i += 1
        return tok

    def kw(self, name: str) -> bool:
        tok = self.peek()
        return tok is not None and tok.kind == "word" and tok.value.lower() == name

    def parse(self) -> Node:
        node = self.or_expr(0)
        if self.peek() is not None:
            raise bad_filter("Unexpected token in filter")
        return node

    def or_expr(self, depth: int) -> Node:
        node = self.and_expr(depth)
        while self.kw("or"):
            self.next()
            node = ("or", node, self.and_expr(depth))
        return node

    def and_expr(self, depth: int) -> Node:
        node = self.atom(depth)
        while self.kw("and"):
            self.next()
            node = ("and", node, self.atom(depth))
        return node

    def comparison(self, attr: str) -> Node:
        op_tok = self.next()
        if op_tok.kind != "word":
            raise bad_filter("Expected an operator in filter")
        op = op_tok.value.lower()
        if op == "pr":
            return ("pr", attr)
        if op not in COMPARE_OPS:
            raise bad_filter(f"Unknown operator '{op_tok.value}'")
        v = self.next()
        if v.kind == "str":
            return ("cmp", attr, op, v.value)
        if v.kind == "word" and v.value.lower() in ("true", "false"):
            return ("cmp", attr, op, v.value.lower() == "true")
        if v.kind == "word" and v.value.lower() == "null":
            return ("cmp", attr, op, None)
        raise bad_filter("Filter values must be quoted strings, true, false or null")

    def atom(self, depth: int, inside_path: bool = False) -> Node:
        tok = self.next()
        if tok.kind == "lp":
            if depth + 1 > MAX_DEPTH:
                raise bad_filter("Filter is nested too deeply")
            node = self.or_expr(depth + 1) if not inside_path else self.path_or(depth + 1)
            if self.next().kind != "rp":
                raise bad_filter("Missing closing parenthesis in filter")
            return node
        if tok.kind != "word":
            raise bad_filter("Expected an attribute name in filter")
        low = tok.value.lower()
        if low == "not":
            if depth + 1 > MAX_DEPTH:
                raise bad_filter("Filter is nested too deeply")
            if self.next().kind != "lp":
                raise bad_filter("'not' must be followed by a parenthesised filter")
            node = self.or_expr(depth + 1) if not inside_path else self.path_or(depth + 1)
            if self.next().kind != "rp":
                raise bad_filter("Missing closing parenthesis in filter")
            return ("not", node)
        if low in ("and", "or"):
            raise bad_filter(f"'{tok.value}' is not supported here")
        attr = tok.value
        nxt = self.peek()
        if nxt is not None and nxt.kind == "lb":
            if inside_path:
                raise bad_filter("Value-path filters cannot be nested")
            self.next()
            sub = self.path_or(depth + 1)
            if self.next().kind != "rb":
                raise bad_filter("Missing closing bracket in filter")
            tail = None
            after = self.peek()
            if after is not None and after.kind == "word" and after.value.startswith("."):
                self.next()
                tail = self.comparison(attr + after.value)
            return ("path", attr, sub, tail)
        return self.comparison(attr)

    # inside [ ... ] the same grammar applies, but valuePaths may not nest
    def path_or(self, depth: int) -> Node:
        node = self.path_and(depth)
        while self.kw("or"):
            self.next()
            node = ("or", node, self.path_and(depth))
        return node

    def path_and(self, depth: int) -> Node:
        node = self.atom(depth, inside_path=True)
        while self.kw("and"):
            self.next()
            node = ("and", node, self.atom(depth, inside_path=True))
        return node


def parse(text: str) -> Node:
    if not text or not text.strip():
        raise bad_filter("Empty filter")
    return _Parser(tokenize(text)).parse()


@dataclass
class Attr:
    """How one filterable attribute maps to SQL. `expr` is a column (string kind) or a boolean expression."""

    kind: str  # "str" | "bool" | "date"
    expr: Any = None
    present: Any = None  # SQL expression for `pr`; defaults to expr IS NOT NULL / non-empty
    exists: Optional[Callable[[Callable[[Any], Any]], Any]] = None  # for multi-valued (members.value): builder(pred)


def _like_escape(v: str) -> str:
    return v.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _str_cond(attr: Attr, op: str, value: Any):
    if attr.exists is not None:
        def pred(col):
            return _str_pred(col, op if op != "ne" else "eq", value)
        cond = attr.exists(pred)
        return ~cond if op == "ne" else cond
    return _str_pred(attr.expr, op, value) if op != "ne" else or_(attr.expr.is_(None), ~_str_pred(attr.expr, "eq", value))


def _str_pred(col, op: str, value: Any):
    if not isinstance(value, str):
        return false()
    lv = value.lower()
    c = func.lower(col)
    if op == "eq":
        return c == lv
    esc = _like_escape(lv)
    if op == "co":
        return c.like(f"%{esc}%", escape="\\")
    if op == "sw":
        return c.like(f"{esc}%", escape="\\")
    return c.like(f"%{esc}", escape="\\")  # ew


def _prefixed(node: Node, prefix: str) -> Node:
    """Inside `attr[ ... ]` every name refers to a sub-attribute: rewrite `type` to `attr.type`."""
    kind = node[0]
    if kind in ("and", "or"):
        return (kind, _prefixed(node[1], prefix), _prefixed(node[2], prefix))
    if kind == "not":
        return ("not", _prefixed(node[1], prefix))
    if kind == "pr":
        return ("pr", f"{prefix}.{node[1]}")
    return ("cmp", f"{prefix}.{node[1]}", node[2], node[3])


def _parse_date(value: Any) -> datetime:
    if not isinstance(value, str):
        raise bad_filter("Date values must be quoted ISO 8601 strings")
    try:
        d = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise bad_filter("Date values must be ISO 8601, e.g. 2024-05-01T12:00:00Z")
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


_ORDER = {"gt": lambda c, v: c > v, "ge": lambda c, v: c >= v, "lt": lambda c, v: c < v, "le": lambda c, v: c <= v}


def compile_filter(node: Node, attrs: Dict[str, Attr]):
    """Turn the AST into a SQLAlchemy boolean expression, rejecting attributes that are not allow-listed."""
    kind = node[0]
    if kind in ("and", "or"):
        l, r = compile_filter(node[1], attrs), compile_filter(node[2], attrs)
        return and_(l, r) if kind == "and" else or_(l, r)
    if kind == "not":
        return ~func.coalesce(compile_filter(node[1], attrs), false())  # NULL counts as "does not match", so not(...) includes it
    if kind == "path":
        _, attr, sub, tail = node
        if attr.lower() not in attrs and f"{attr.lower()}.value" not in attrs and not any(k.startswith(attr.lower() + ".") for k in attrs):
            raise bad_filter(f"Filtering on '{attr}' is not supported")
        cond = compile_filter(_prefixed(sub, attr), attrs)
        return and_(cond, compile_filter(tail, attrs)) if tail is not None else cond
    attr = attrs.get(node[1].lower())
    if attr is None:
        raise bad_filter(f"Filtering on '{node[1]}' is not supported")
    if kind == "pr":
        if attr.expr is None and attr.present is None:
            raise bad_filter(f"'pr' is not supported for '{node[1]}'")
        if attr.present is not None:
            return attr.present
        if attr.kind == "bool":
            return true()
        if attr.kind == "date":
            return attr.expr.is_not(None)
        return and_(attr.expr.is_not(None), attr.expr != "")
    _, _, op, value = node
    if attr.kind == "date":
        if value is None:
            if op not in ("eq", "ne"):
                raise bad_filter("null is only valid with eq/ne")
            return attr.expr.is_(None) if op == "eq" else attr.expr.is_not(None)
        if op in ("co", "sw", "ew"):
            raise bad_filter(f"Operator '{op}' does not apply to dates")
        d = _parse_date(value)
        if op == "eq":
            return attr.expr == d
        if op == "ne":
            return or_(attr.expr.is_(None), attr.expr != d)
        return _ORDER[op](attr.expr, d)
    if op in ORDER_OPS:
        if attr.kind == "bool" or attr.exists is not None or not isinstance(value, str):
            raise bad_filter(f"Operator '{op}' does not apply to '{node[1]}'")
        return _ORDER[op](func.lower(attr.expr), value.lower())
    if attr.kind == "bool":
        if isinstance(value, str) and value.lower() in ("true", "false"):
            value = value.lower() == "true"  # Entra-style "True"
        if not isinstance(value, bool) or op not in ("eq", "ne"):
            raise bad_filter(f"Attribute '{node[1]}' only supports eq/ne with true or false")
        return attr.expr if (value is (op == "eq")) else ~attr.expr
    if value is None:
        if op not in ("eq", "ne"):
            raise bad_filter("null is only valid with eq/ne")
        return attr.expr.is_(None) if op == "eq" else attr.expr.is_not(None)
    if isinstance(value, bool):
        raise bad_filter(f"Attribute '{node[1]}' is a string")
    return _str_cond(attr, op, value)


def build(text: str, attrs: Dict[str, Attr]):
    return compile_filter(parse(text), attrs)
