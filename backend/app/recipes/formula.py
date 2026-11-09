"""Recipe formulas (ADR 021 section 1): ``{{= upper(trigger.user.last_name) }}``.

A small, closed expression language that we parse and evaluate ourselves. There is no ``eval``, no attribute access,
no way to name anything except a datapill path or one of the functions in ``FUNCTIONS``, and no I/O: every function
is a pure computation over the values it is given. Limits (length, depth, evaluation steps, output size) are hard.

Taint: the evaluator reads datapills only through the ``read`` callback the caller supplies, so the caller's taint
check sees every path a formula touches (at save time through ``paths()``, at run time through ``read``). A formula
that reads a value a user can edit is therefore refused wherever a plain datapill with that value would be.

Grammar (lowest precedence first)::

    expr    := or ( '?' expr ':' expr )?
    or      := and ( 'or' and )*
    and     := not ( 'and' not )*
    not     := 'not' not | compare
    compare := add ( ('==' | '!=' | '<' | '<=' | '>' | '>=') add )?
    add     := mul ( ('+' | '-') mul )*
    mul     := unary ( ('*' | '/' | '%') unary )*
    unary   := '-' unary | primary
    primary := number | 'text' | "text" | true | false | null | '[' items ']' | name '(' args ')' | datapill.path | '(' expr ')'
"""

import base64
import hashlib
import json
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote

MAX_EXPRESSION = 2000
MAX_DEPTH = 20
MAX_OPERATIONS = 10_000
MAX_TEXT = 65_536
MAX_ITEMS = 5_000


class FormulaError(ValueError):
    """Bad formula or a value it cannot work with. The message is safe to show to administrators."""


# ---- parsing ---------------------------------------------------------------------------------------------------

_TOKEN = re.compile(
    r"""\s*(?:(?P<num>\d+(?:\.\d+)?)
            |(?P<str>'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")
            |(?P<op>==|!=|<=|>=|[-+*/%<>?:(),\[\]])
            |(?P<name>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*))""",
    re.VERBOSE,
)
_ESCAPES = {"\\": "\\", "'": "'", '"': '"', "n": "\n", "t": "\t"}
_KEYWORDS = {"and", "or", "not", "true", "false", "null"}


def _unescape(raw: str) -> str:
    body, out, i = raw[1:-1], [], 0
    while i < len(body):
        c = body[i]
        if c == "\\":
            i += 1
            if body[i] not in _ESCAPES:
                raise FormulaError(f"unknown escape \\{body[i]} in text")
            out.append(_ESCAPES[body[i]])
        else:
            out.append(c)
        i += 1
    return "".join(out)


def _tokens(src: str) -> List[Tuple[str, Any, int]]:
    out, pos = [], 0
    src = src.rstrip()
    while pos < len(src):
        m = _TOKEN.match(src, pos)
        if not m or m.end() == pos:
            raise FormulaError(f"unexpected character at position {pos + 1}: {src[pos:pos + 1]!r}")
        kind = m.lastgroup
        text = m.group(kind)
        start = m.start(kind)
        if kind == "num":
            out.append(("num", float(text) if "." in text else int(text), start))
        elif kind == "str":
            out.append(("str", _unescape(text), start))
        elif kind == "op":
            out.append(("op", text, start))
        else:
            out.append(("name", text, start))
        pos = m.end()
    return out


class _Parser:
    def __init__(self, src: str):
        if len(src) > MAX_EXPRESSION:
            raise FormulaError(f"a formula can be at most {MAX_EXPRESSION} characters")
        self.t = _tokens(src)
        self.i = 0
        self.depth = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else ("end", None, -1)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def op(self, *ops) -> Optional[str]:
        k, v, _ = self.peek()
        if k == "op" and v in ops:
            self.i += 1
            return v
        return None

    def word(self, w: str) -> bool:
        k, v, _ = self.peek()
        if k == "name" and v == w:
            self.i += 1
            return True
        return False

    def enter(self):
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise FormulaError("the formula is nested too deeply")

    def leave(self):
        self.depth -= 1

    def parse(self):
        if not self.t:
            raise FormulaError("the formula is empty")
        node = self.expr()
        if self.i != len(self.t):
            k, v, pos = self.peek()
            raise FormulaError(f"unexpected {v!r} at position {pos + 1}")
        return node

    def expr(self):
        self.enter()
        node = self.or_()
        if self.op("?"):
            a = self.expr()
            if not self.op(":"):
                raise FormulaError("expected ':' in the ? : expression")
            b = self.expr()
            node = ("if", node, a, b)
        self.leave()
        return node

    def or_(self):
        node = self.and_()
        while self.word("or"):
            node = ("or", node, self.and_())
        return node

    def and_(self):
        node = self.not_()
        while self.word("and"):
            node = ("and", node, self.not_())
        return node

    def not_(self):
        if self.word("not"):
            self.enter()
            node = ("not", self.not_())
            self.leave()
            return node
        return self.compare()

    def compare(self):
        node = self.add()
        o = self.op("==", "!=", "<=", ">=", "<", ">")
        if o:
            node = ("cmp", o, node, self.add())
        return node

    def add(self):
        node = self.mul()
        while True:
            o = self.op("+", "-")
            if not o:
                return node
            node = ("bin", o, node, self.mul())

    def mul(self):
        node = self.unary()
        while True:
            o = self.op("*", "/", "%")
            if not o:
                return node
            node = ("bin", o, node, self.unary())

    def unary(self):
        if self.op("-"):
            self.enter()
            node = ("neg", self.unary())
            self.leave()
            return node
        return self.primary()

    def primary(self):
        kind, val, pos = self.take()
        if kind == "num" or kind == "str":
            return ("lit", val)
        if kind == "op" and val == "[":
            items: List[Any] = []
            if not self.op("]"):
                while True:
                    items.append(self.expr())
                    if self.op("]"):
                        break
                    if not self.op(","):
                        raise FormulaError("expected ',' or ']' in the list")
            if len(items) > 200:
                raise FormulaError("a list in a formula can have at most 200 items")
            return ("list", items)
        if kind == "op" and val == "(":
            node = self.expr()
            if not self.op(")"):
                raise FormulaError("missing ')'")
            return node
        if kind == "name":
            if val in ("true", "false", "null"):
                return ("lit", {"true": True, "false": False, "null": None}[val])
            if val in _KEYWORDS:
                raise FormulaError(f"unexpected '{val}' at position {pos + 1}")
            if self.op("("):
                if "." in val:
                    raise FormulaError(f"'{val}' is not a function (functions have no dots)")
                args: List[Any] = []
                if not self.op(")"):
                    while True:
                        args.append(self.expr())
                        if self.op(")"):
                            break
                        if not self.op(","):
                            raise FormulaError(f"expected ',' or ')' in the arguments of {val}()")
                if val not in FUNCTIONS:
                    raise FormulaError(f"unknown function '{val}'")
                lo, hi = FUNCTIONS[val][0], FUNCTIONS[val][1]
                if not lo <= len(args) <= hi:
                    raise FormulaError(f"{val}() takes {lo if lo == hi else f'{lo} to {hi}'} argument(s), not {len(args)}")
                return ("call", val, args)
            if "." not in val:
                raise FormulaError(f"unknown name '{val}' (datapills look like trigger.user.email)")
            return ("path", val)
        raise FormulaError("the formula ended unexpectedly" if kind == "end" else f"unexpected {val!r} at position {pos + 1}")


def parse(source: str):
    """Parse a formula into an AST (nested tuples). Raises FormulaError."""
    return _Parser(source).parse()


def paths(node) -> List[str]:
    """Every datapill path the formula reads (so the caller can validate and taint-check them)."""
    out: List[str] = []

    def walk(n):
        k = n[0]
        if k == "path":
            out.append(n[1])
        elif k == "call":
            for a in n[2]:
                walk(a)
        elif k == "list":
            for a in n[1]:
                walk(a)
        elif k in ("lit",):
            return
        else:
            for c in n[1:]:
                if isinstance(c, tuple):
                    walk(c)

    walk(node)
    return out


# ---- values ----------------------------------------------------------------------------------------------------

def text_of(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, (dict, list)):
        return json.dumps(v, separators=(",", ":"), sort_keys=True)
    return str(v)


def _num(v: Any, what: str = "a number") -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        if isinstance(v, str):
            try:
                return float(v) if "." in v else int(v)
            except ValueError:
                pass
        raise FormulaError(f"expected {what}, got {_kind(v)}")
    return v


def _str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        raise FormulaError(f"expected text, got {_kind(v)}")
    return text_of(v)


def _list(v: Any) -> list:
    if not isinstance(v, list):
        raise FormulaError(f"expected a list, got {_kind(v)}")
    return v


def _kind(v: Any) -> str:
    return "nothing" if v is None else "true/false" if isinstance(v, bool) else "a number" if isinstance(v, (int, float)) else "text" if isinstance(v, str) else "a list" if isinstance(v, list) else "an object"


def truthy(v: Any) -> bool:
    return not (v is None or v is False or v == 0 or v == "" or v == [] or v == {})


def _clip(v: Any) -> Any:
    if isinstance(v, str) and len(v) > MAX_TEXT:
        raise FormulaError("the result is too long")
    if isinstance(v, list) and len(v) > MAX_ITEMS:
        raise FormulaError("the list is too long")
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        raise FormulaError("the result is not a finite number")
    return v


def _now() -> datetime:  # a seam for tests
    return datetime.now(timezone.utc)


def _when(v: Any) -> Tuple[datetime, bool]:
    s = _str(v).strip()
    try:
        if len(s) == 10:
            return datetime.fromisoformat(s).replace(tzinfo=timezone.utc), True
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        raise FormulaError(f"'{s[:40]}' is not a date (use 2030-01-31 or 2030-01-31T12:00:00Z)")
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc), False


def _iso(d: datetime, date_only: bool) -> str:
    return d.date().isoformat() if date_only else d.strftime("%Y-%m-%dT%H:%M:%SZ")


_FMT_OK = set("YmdHMSBbAaejyZ%")


def _format_date(d, fmt):
    f = _str(fmt)
    for m in re.finditer(r"%(.)", f):
        if m.group(1) not in _FMT_OK:
            raise FormulaError(f"the date format %{m.group(1)} is not supported")
    return _when(d)[0].strftime(f)


def _substring(t, start, length=None):
    s, a = _str(t), int(_num(start))
    a = max(a, 0)
    return s[a:] if length is None else s[a: a + max(int(_num(length)), 0)]


def _round(x, digits=0):
    d = int(_num(digits))
    r = round(float(_num(x)), d)
    return int(r) if d <= 0 else r


def _get(obj, key):
    if isinstance(obj, dict):
        return obj.get(_str(key))
    if isinstance(obj, list):
        i = int(_num(key))
        return obj[i] if -len(obj) <= i < len(obj) else None
    if obj is None:
        return None
    raise FormulaError(f"get() needs a list or an object, got {_kind(obj)}")


def _canon(v):
    return json.dumps(v, sort_keys=True, default=str)


def _uniq(l):
    seen, out = set(), []
    for x in _list(l):
        k = _canon(x)
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out


def _flatten(l, depth=0):
    if depth > 20:
        raise FormulaError("the list is nested too deeply")
    out = []
    for x in _list(l):
        out.extend(_flatten(x, depth + 1) if isinstance(x, list) else [x])
        if len(out) > MAX_ITEMS:
            raise FormulaError("the list is too long")
    return out


def _concat(*lists):
    out = []
    for l in lists:
        out.extend(_list(l))
        if len(out) > MAX_ITEMS:
            raise FormulaError("the list is too long")
    return out


def _pluck(l, key):
    return [_get(x, key) for x in _list(l)]


def _reverse(v):
    return v[::-1] if isinstance(v, list) else _str(v)[::-1]


def _index(l, x):
    for i, y in enumerate(_list(l)):
        if (_both_num(x, y) and x == y) or (type(x) is type(y) and x == y):
            return i
    return None


def _numbers(a):
    """min(a, b, ...) or min(list): the numbers to compare; an empty list has none."""
    items = a[0] if len(a) == 1 and isinstance(a[0], list) else a
    return [_num(x) for x in items]


def _min(*a):
    n = _numbers(a)
    return min(n) if n else None


def _max(*a):
    n = _numbers(a)
    return max(n) if n else None


def _contains(h, x):
    if isinstance(h, list):
        return x in h
    return _str(x) in _str(h)


def _split(t, sep=","):
    s, p = _str(t), _str(sep)
    if p == "":
        raise FormulaError("split() needs a separator")
    return s.split(p)[:MAX_ITEMS]


def _json_parse(t):
    s = _str(t)
    if len(s) > MAX_TEXT:
        raise FormulaError("the JSON text is too long")
    try:
        return json.loads(s)
    except ValueError:
        raise FormulaError("that is not valid JSON")


def _email_part(email, which):
    s = _str(email).strip()
    if "@" not in s:
        return ""
    local, _, dom = s.rpartition("@")
    return dom.lower() if which == "domain" else local


def _b64d(t):
    try:
        return base64.b64decode(_str(t), validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        raise FormulaError("that is not valid base64 text")


# name: (min args, max args, implementation, signature, description, example)
# `if` and `coalesce` are evaluated lazily by the evaluator; their implementations are placeholders.
_ANY = 99
FUNCTIONS: Dict[str, Tuple[int, int, Optional[Callable], str, str, str]] = {
    # text
    "upper": (1, 1, lambda t: _str(t).upper(), "upper(text)", "Upper case", 'upper("Ann") → "ANN"'),
    "lower": (1, 1, lambda t: _str(t).lower(), "lower(text)", "Lower case", 'lower("Ann") → "ann"'),
    "trim": (1, 1, lambda t: _str(t).strip(), "trim(text)", "Remove spaces at both ends", 'trim("  a ") → "a"'),
    "length": (1, 1, lambda v: len(v) if isinstance(v, (list, dict)) else len(_str(v)), "length(text or list)", "Number of characters or items", 'length("abc") → 3'),
    "contains": (2, 2, _contains, "contains(text or list, value)", "True if the text or list holds the value", 'contains("a@b.com", "@") → true'),
    "starts_with": (2, 2, lambda t, p: _str(t).startswith(_str(p)), "starts_with(text, prefix)", "True if the text starts with the prefix", 'starts_with("abc", "a") → true'),
    "ends_with": (2, 2, lambda t, p: _str(t).endswith(_str(p)), "ends_with(text, suffix)", "True if the text ends with the suffix", 'ends_with("abc", "c") → true'),
    "replace": (3, 3, lambda t, a, b: _str(t).replace(_str(a), _str(b)), "replace(text, find, with)", "Replace every occurrence (plain text, not a pattern)", 'replace("a-b", "-", "_") → "a_b"'),
    "substring": (2, 3, _substring, "substring(text, start, length?)", "Part of a text (start at 0)", 'substring("abcdef", 1, 3) → "bcd"'),
    "split": (1, 2, _split, "split(text, separator?)", "Split a text into a list (default separator is a comma)", 'split("a,b") → ["a","b"]'),
    "join": (1, 2, lambda l, s=",": _str(s).join(text_of(x) for x in _list(l)), "join(list, separator?)", "Join a list into one text", 'join(["a","b"], "-") → "a-b"'),
    "text": (1, 1, text_of, "text(value)", "Turn any value into text", "text(42) → \"42\""),
    "email_domain": (1, 1, lambda e: _email_part(e, "domain"), "email_domain(email)", "The part after the @, lower case", 'email_domain("a@Corp.com") → "corp.com"'),
    "email_name": (1, 1, lambda e: _email_part(e, "name"), "email_name(email)", "The part before the @", 'email_name("ann@corp.com") → "ann"'),
    # numbers
    "number": (1, 1, _num, "number(value)", "Turn text into a number", 'number("42") → 42'),
    "round": (1, 2, _round, "round(number, digits?)", "Round to a number of decimals (default 0)", "round(2.567, 1) → 2.6"),
    "floor": (1, 1, lambda x: math.floor(_num(x)), "floor(number)", "Round down", "floor(2.9) → 2"),
    "ceil": (1, 1, lambda x: math.ceil(_num(x)), "ceil(number)", "Round up", "ceil(2.1) → 3"),
    "abs": (1, 1, lambda x: abs(_num(x)), "abs(number)", "Absolute value", "abs(-3) → 3"),
    "min": (1, _ANY, _min, "min(a, b, ...) or min(list)", "Smallest number", "min(3, 1) → 1"),
    "max": (1, _ANY, _max, "max(a, b, ...) or max(list)", "Largest number", "max(3, 1) → 3"),
    # dates (ISO text: 2030-01-31 or 2030-01-31T12:00:00Z)
    "now": (0, 0, lambda: _iso(_now(), False), "now()", "The current date and time (UTC)", "now()"),
    "today": (0, 0, lambda: _now().date().isoformat(), "today()", "Today's date (UTC)", "today()"),
    "add_days": (2, 2, lambda d, n: _iso(_when(d)[0] + timedelta(days=int(_num(n))), _when(d)[1]), "add_days(date, days)", "Add (or subtract) days", 'add_days("2030-01-30", 2) → "2030-02-01"'),
    "diff_days": (2, 2, lambda a, b: (_when(a)[0] - _when(b)[0]).days, "diff_days(later, earlier)", "Whole days between two dates", 'diff_days("2030-02-01", "2030-01-30") → 2'),
    "format_date": (2, 2, _format_date, "format_date(date, format)", "Format a date (%Y %m %d %H %M %S %B %b %A %a %e %j %y %Z)", 'format_date("2030-01-31", "%d %B %Y") → "31 January 2030"'),
    "parse_date": (1, 1, lambda d: _iso(*_when(d)), "parse_date(text)", "Check and normalise a date", 'parse_date("2030-01-31") → "2030-01-31"'),
    # lists and objects
    "first": (1, 1, lambda l: (_list(l) or [None])[0], "first(list)", "First item", 'first(["a","b"]) → "a"'),
    "last": (1, 1, lambda l: (_list(l) or [None])[-1], "last(list)", "Last item", 'last(["a","b"]) → "b"'),
    "count": (1, 1, lambda l: len(_list(l)), "count(list)", "Number of items", 'count(["a","b"]) → 2'),
    "index": (2, 2, _index, "index(list, value)", "Position of the first match (starting at 0), or nothing", 'index(["a","b"], "b") → 1'),
    "reverse": (1, 1, _reverse, "reverse(list or text)", "Reverse the order", 'reverse([1,2,3]) → [3,2,1]'),
    "sum": (1, 1, lambda l: _clip(sum(_num(x) for x in _list(l))), "sum(list)", "Add up a list of numbers", "sum([1,2,3]) → 6"),
    "uniq": (1, 1, _uniq, "uniq(list)", "Remove repeated items, keeping the first", 'uniq(["a","b","a"]) → ["a","b"]'),
    "flatten": (1, 1, _flatten, "flatten(list)", "Merge nested lists into one", "flatten([[1],[2,[3]]]) → [1,2,3]"),
    "compact": (1, 1, lambda l: [x for x in _list(l) if x is not None], "compact(list)", "Remove empty (nothing) items", "compact([1, null]) → [1]"),
    "concat": (1, _ANY, _concat, "concat(list, list, ...)", "Join lists end to end", "concat([1],[2]) → [1,2]"),
    "pluck": (2, 2, _pluck, "pluck(list of objects, key)", "One value from every object in a list", 'pluck(json_parse("[{\\"a\\":1}]"), "a") → [1]'),
    "smart_join": (2, 2, lambda l, sep: _str(sep).join(_str(x) for x in _list(l) if not (x is None or x == "")), "smart_join(list, separator)", "Join the items that are not empty", 'smart_join(["a","","b"], "-") → "a-b"'),
    "get": (2, 2, _get, "get(object or list, key or position)", "Read one entry; nothing when it is missing", 'get(trigger.payload, "id")'),
    # logic
    "if": (3, 3, None, "if(condition, then, otherwise)", "Pick a value (only the chosen one is evaluated)", 'if(length(a) > 3, "long", "short")'),
    "coalesce": (1, _ANY, None, "coalesce(a, b, ...)", "The first value that is not empty", 'coalesce(trigger.user.attributes.nickname, "friend")'),
    "is_blank": (1, 1, lambda v: v is None or v == "" or v == [] or v == {}, "is_blank(value)", "True when the value is missing or empty", "is_blank(\"\") → true"),
    # encoding
    "base64_encode": (1, 1, lambda t: base64.b64encode(_str(t).encode()).decode(), "base64_encode(text)", "Base64 text", 'base64_encode("a") → "YQ=="'),
    "base64_decode": (1, 1, _b64d, "base64_decode(text)", "Decode base64 text", 'base64_decode("YQ==") → "a"'),
    "url_encode": (1, 1, lambda t: quote(_str(t), safe=""), "url_encode(text)", "Make a text safe for a URL", 'url_encode("a b") → "a%20b"'),
    "sha256": (1, 1, lambda t: hashlib.sha256(_str(t).encode()).hexdigest(), "sha256(text)", "SHA-256 hash as hex", 'sha256("a")'),
    "json_parse": (1, 1, _json_parse, "json_parse(text)", "Read JSON text into a value", 'json_parse("{\\"a\\":1}")'),
    "json_stringify": (1, 1, lambda v: json.dumps(v, separators=(",", ":"), sort_keys=True), "json_stringify(value)", "Write a value as JSON text", "json_stringify([1,2]) → \"[1,2]\""),
}

CATALOG = [{"name": n, "signature": f[3], "description": f[4], "example": f[5]} for n, f in FUNCTIONS.items()]


# ---- evaluation ------------------------------------------------------------------------------------------------

def evaluate(node, read: Callable[[str], Any]) -> Any:
    """Evaluate a parsed formula. ``read(path)`` returns a datapill's value (None when it has none)."""
    ops = [0]

    def ev(n):
        ops[0] += 1
        if ops[0] > MAX_OPERATIONS:
            raise FormulaError("the formula is too expensive to evaluate")
        k = n[0]
        if k == "lit":
            return n[1]
        if k == "path":
            return read(n[1])
        if k == "list":
            return [ev(a) for a in n[1]]
        if k == "not":
            return not truthy(ev(n[1]))
        if k == "neg":
            return -_num(ev(n[1]))
        if k == "and":
            return truthy(ev(n[1])) and truthy(ev(n[2]))
        if k == "or":
            return truthy(ev(n[1])) or truthy(ev(n[2]))
        if k == "if":
            return ev(n[2]) if truthy(ev(n[1])) else ev(n[3])
        if k == "cmp":
            a, b = ev(n[2]), ev(n[3])
            if n[1] in ("==", "!="):
                same = a == b if _both_num(a, b) else (type(a) is type(b) and a == b)
                return same if n[1] == "==" else not same
            if _both_num(a, b) or (isinstance(a, str) and isinstance(b, str)):
                return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[n[1]]
            raise FormulaError(f"cannot compare {_kind(a)} with {_kind(b)}")
        if k == "bin":
            a, b = ev(n[2]), ev(n[3])
            if n[1] == "+" and isinstance(a, str) and isinstance(b, str):
                return _clip(a + b)
            x, y = _num(a), _num(b)
            if n[1] == "+":
                return _clip(x + y)
            if n[1] == "-":
                return _clip(x - y)
            if n[1] == "*":
                return _clip(x * y)
            if y == 0:
                raise FormulaError("division by zero")
            return _clip(x / y if n[1] == "/" else x % y)
        if k == "call":
            name, args = n[1], n[2]
            if name == "if":
                return ev(args[1]) if truthy(ev(args[0])) else ev(args[2])
            if name == "coalesce":
                for a in args:
                    v = ev(a)
                    if not (v is None or v == ""):
                        return v
                return None
            fn = FUNCTIONS[name][2]
            try:
                return _clip(fn(*[ev(a) for a in args]))
            except FormulaError:
                raise
            except (TypeError, ValueError, OverflowError, IndexError, KeyError) as e:
                raise FormulaError(f"{name}() could not use those values") from e
        raise FormulaError("unsupported expression")  # pragma: no cover

    return ev(node)


def _both_num(a, b) -> bool:
    return all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (a, b))
