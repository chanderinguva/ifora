"""A safe subset of the Okta Expression Language for group rules.

    user.department == "Sales" && user.userType != "Contractor"
    String.stringContains(user.email, "@example.com") || user.costCenter == "C100"
    Arrays.contains({"a","b"} , user.division)  -- (use  user.division == "a" || user.division == "b")

Parsed by a small hand-written parser and evaluated over a fixed AST. There is no eval, no reflection and no
method call on arbitrary objects: only `user.<attribute>` reads and the whitelisted functions below. Limits on length,
nodes and nesting keep evaluation bounded. Comparisons are case-sensitive like Okta's.

Supported: literals (strings in ' or ", numbers, true, false, null), == != < <= > >= (and eq ne lt le gt ge),
&& || ! (and and or not), parentheses, `cond ? a : b`, and the functions in FUNCTIONS. Attribute names may be Okta's
camelCase (user.employeeNumber) or ours (user.employee_number); user.login is the username.
Not supported: group-membership functions (isMemberOfGroup...), app user attributes, arrays literals.
"""

import re
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

MAX_LENGTH = 1000
MAX_NODES = 150
MAX_DEPTH = 20
MAX_STRING = 1000


class ElError(ValueError):
    """Syntax or evaluation problem; the message is safe to show to an administrator."""


_TOKEN = re.compile(
    r"""\s*(?:(?P<num>\d+(?:\.\d+)?)|(?P<str>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|(?P<id>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)"""
    r"""|(?P<op>==|!=|<=|>=|&&|\|\||[<>!?:(),]))"""
)
_WORD_OPS = {"eq": "==", "ne": "!=", "lt": "<", "le": "<=", "gt": ">", "ge": ">=", "and": "&&", "or": "||", "not": "!"}


def _tokens(src: str) -> List[Tuple[str, Any]]:
    if len(src) > MAX_LENGTH:
        raise ElError(f"expression is limited to {MAX_LENGTH} characters")
    pos, out = 0, []
    src = src.rstrip()
    while pos < len(src):
        m = _TOKEN.match(src, pos)
        if not m or m.end() == pos:
            raise ElError(f"unexpected character at position {pos + 1}")
        pos = m.end()
        if m.group("num") is not None:
            t = m.group("num")
            out.append(("lit", float(t) if "." in t else int(t)))
        elif m.group("str") is not None:
            body = m.group("str")[1:-1]
            if len(body) > 200:
                raise ElError("string literals are limited to 200 characters")
            out.append(("lit", re.sub(r"\\(.)", r"\1", body)))
        elif m.group("id") is not None:
            w = m.group("id")
            if w == "true":
                out.append(("lit", True))
            elif w == "false":
                out.append(("lit", False))
            elif w == "null":
                out.append(("lit", None))
            elif w in _WORD_OPS:
                out.append(("op", _WORD_OPS[w]))
            else:
                out.append(("id", w))
        else:
            out.append(("op", m.group("op")))
    return out


class _Parser:
    def __init__(self, tokens: List[Tuple[str, Any]]):
        self.t, self.i, self.nodes = tokens, 0, 0

    def peek(self) -> Optional[Tuple[str, Any]]:
        return self.t[self.i] if self.i < len(self.t) else None

    def take_op(self, *ops: str) -> Optional[str]:
        p = self.peek()
        if p and p[0] == "op" and p[1] in ops:
            self.i += 1
            return p[1]
        return None

    def node(self, *n):
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise ElError(f"expression is too complex (more than {MAX_NODES} parts)")
        return n

    def parse(self):
        if not self.t:
            raise ElError("expression is empty")
        n = self.ternary(0)
        if self.peek() is not None:
            raise ElError("unexpected text after the end of the expression")
        return n

    def ternary(self, depth):
        if depth > MAX_DEPTH:
            raise ElError("expression is nested too deeply")
        c = self.or_(depth)
        if self.take_op("?"):
            a = self.ternary(depth + 1)
            if not self.take_op(":"):
                raise ElError("expected ':' in a ? : expression")
            return self.node("if", c, a, self.ternary(depth + 1))
        return c

    def or_(self, d):
        n = self.and_(d)
        while self.take_op("||"):
            n = self.node("or", n, self.and_(d))
        return n

    def and_(self, d):
        n = self.eq(d)
        while self.take_op("&&"):
            n = self.node("and", n, self.eq(d))
        return n

    def eq(self, d):
        n = self.rel(d)
        while (op := self.take_op("==", "!=")):
            n = self.node("cmp", op, n, self.rel(d))
        return n

    def rel(self, d):
        n = self.unary(d)
        while (op := self.take_op("<", "<=", ">", ">=")):
            n = self.node("cmp", op, n, self.unary(d))
        return n

    def unary(self, d):
        if d > MAX_DEPTH:
            raise ElError("expression is nested too deeply")
        if self.take_op("!"):
            return self.node("not", self.unary(d + 1))
        return self.primary(d)

    def primary(self, d):
        p = self.peek()
        if p is None:
            raise ElError("expression ends unexpectedly")
        self.i += 1
        if p[0] == "lit":
            return self.node("lit", p[1])
        if p[0] == "op" and p[1] == "(":
            n = self.ternary(d + 1)
            if not self.take_op(")"):
                raise ElError("missing ')'")
            return n
        if p[0] == "id":
            name = p[1]
            if self.take_op("("):
                args = []
                if not self.take_op(")"):
                    while True:
                        args.append(self.ternary(d + 1))
                        if self.take_op(")"):
                            break
                        if not self.take_op(","):
                            raise ElError("expected ',' or ')' in function call")
                if name not in FUNCTIONS:
                    raise ElError(f"unknown function '{name}'")
                lo, hi, _ = FUNCTIONS[name]
                if not lo <= len(args) <= hi:
                    raise ElError(f"{name} takes {lo if lo == hi else f'{lo} to {hi}'} argument(s)")
                return self.node("call", name, tuple(args))
            parts = name.split(".")
            if parts[0] != "user" or len(parts) != 2:
                raise ElError(f"'{name}' is not available; use user.<attribute>")
            return self.node("attr", _snake(parts[1]))
        raise ElError(f"unexpected '{p[1]}'")


def _snake(name: str) -> str:
    if name == "login":
        return "username"
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def parse(src: str):
    return _Parser(_tokens(src)).parse()


def attributes(ast) -> Set[str]:
    """Every user attribute the expression reads."""
    found: Set[str] = set()

    def walk(n):
        if n[0] == "attr":
            found.add(n[1])
        elif n[0] == "call":
            for a in n[2]:
                walk(a)
        elif n[0] in ("and", "or"):
            walk(n[1]); walk(n[2])
        elif n[0] == "not":
            walk(n[1])
        elif n[0] == "cmp":
            walk(n[2]); walk(n[3])
        elif n[0] == "if":
            for x in n[1:]:
                walk(x)

    walk(ast)
    return found


# ---- functions ---------------------------------------------------------------------------

def _s(v: Any) -> str:
    return "" if v is None else (str(v).lower() if isinstance(v, bool) else str(v))


def _cap(s: str) -> str:
    if len(s) > MAX_STRING:
        raise ElError("string too long")
    return s


def _int(v: Any) -> Optional[int]:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _switch(s, default, *pairs):
    if len(pairs) % 2:
        raise ElError("String.stringSwitch needs key/value pairs")
    for k, v in zip(pairs[::2], pairs[1::2]):
        if _s(k) in _s(s):
            return v
    return default


FUNCTIONS: Dict[str, Tuple[int, int, Callable]] = {
    "String.stringContains": (2, 2, lambda s, sub: _s(sub) in _s(s)),
    "String.len": (1, 1, lambda s: len(_s(s))),
    "String.toUpperCase": (1, 1, lambda s: _s(s).upper()),
    "String.toLowerCase": (1, 1, lambda s: _s(s).lower()),
    "String.substring": (3, 3, lambda s, a, b: _s(s)[max(_int(a) or 0, 0):max(_int(b) or 0, 0)]),
    "String.substringBefore": (2, 2, lambda s, sep: _s(s).split(_s(sep), 1)[0] if _s(sep) and _s(sep) in _s(s) else _s(s)),
    "String.substringAfter": (2, 2, lambda s, sep: _s(s).split(_s(sep), 1)[1] if _s(sep) and _s(sep) in _s(s) else ""),
    "String.replace": (3, 3, lambda s, a, b: _cap(_s(s).replace(_s(a), _s(b))) if _s(a) else _s(s)),
    "String.replaceFirst": (3, 3, lambda s, a, b: _cap(_s(s).replace(_s(a), _s(b), 1)) if _s(a) else _s(s)),
    "String.append": (2, 2, lambda a, b: _cap(_s(a) + _s(b))),
    "String.join": (2, 12, lambda sep, *xs: _cap(_s(sep).join(_s(x) for x in xs))),
    "String.stringSwitch": (2, 22, _switch),
    "Convert.toInt": (1, 1, _int),
    "Arrays.isEmpty": (1, 1, lambda a: not a),
    "Arrays.size": (1, 1, lambda a: len(a) if isinstance(a, list) else (0 if a is None else 1)),
    "Arrays.contains": (2, 2, lambda a, v: (v in a) if isinstance(a, list) else (a == v and a is not None)),
}


# Help shown by the rule editor's auto-suggest: (signature, what it does, returns, example). One entry per function;
# a test fails if a function is added without documentation.
HELP: Dict[str, Tuple[str, str, str, str]] = {
    "String.stringContains": ("String.stringContains(text, part)", "True when text contains part (case-sensitive).", "boolean", 'String.stringContains(user.email, "@example.com")'),
    "String.len": ("String.len(text)", "Number of characters.", "number", "String.len(user.employeeId) == 6"),
    "String.toUpperCase": ("String.toUpperCase(text)", "Upper-cases text.", "string", 'String.toUpperCase(user.department) == "SALES"'),
    "String.toLowerCase": ("String.toLowerCase(text)", "Lower-cases text, handy for case-insensitive comparison.", "string", 'String.toLowerCase(user.department) == "sales"'),
    "String.substring": ("String.substring(text, start, end)", "Characters from start up to (not including) end, counting from 0.", "string", 'String.substring(user.employeeId, 0, 2) == "EU"'),
    "String.substringBefore": ("String.substringBefore(text, separator)", "Everything before the first separator (all of text if absent).", "string", 'String.substringBefore(user.email, "@")'),
    "String.substringAfter": ("String.substringAfter(text, separator)", "Everything after the first separator (empty if absent).", "string", 'String.substringAfter(user.email, "@") == "example.com"'),
    "String.replace": ("String.replace(text, find, replacement)", "Replaces every occurrence of find.", "string", 'String.replace(user.costCenter, "-", "")'),
    "String.replaceFirst": ("String.replaceFirst(text, find, replacement)", "Replaces the first occurrence of find.", "string", 'String.replaceFirst(user.costCenter, "C", "")'),
    "String.append": ("String.append(text, suffix)", "Joins two strings.", "string", 'String.append(user.department, "-team")'),
    "String.join": ("String.join(separator, a, b, …)", "Joins up to 11 values with a separator.", "string", 'String.join(" ", user.firstName, user.lastName)'),
    "String.stringSwitch": ("String.stringSwitch(text, default, key1, value1, …)", "Returns the value of the first key that text contains, otherwise default.", "string", 'String.stringSwitch(user.email, "other", "@eu.", "EU", "@us.", "US")'),
    "Convert.toInt": ("Convert.toInt(value)", "Converts text to a whole number (empty if it is not one).", "number", "Convert.toInt(user.level) >= 5"),
    "Arrays.isEmpty": ("Arrays.isEmpty(list)", "True when the list or value is empty.", "boolean", "Arrays.isEmpty(user.managers)"),
    "Arrays.size": ("Arrays.size(list)", "Number of items.", "number", "Arrays.size(user.managers) > 1"),
    "Arrays.contains": ("Arrays.contains(list, value)", "True when the list contains the value.", "boolean", 'Arrays.contains(user.roles, "admin")'),
}

OPERATORS_HELP = [
    ("==", "equals (case-sensitive)"), ("!=", "does not equal"), ("<", "less than"), ("<=", "less than or equal"), (">", "greater than"),
    (">=", "greater than or equal"), ("&&", "and"), ("||", "or"), ("!", "not"), ("?:", "condition ? valueIfTrue : valueIfFalse"),
    ("eq", "same as =="), ("ne", "same as !="), ("lt", "same as <"), ("le", "same as <="), ("gt", "same as >"), ("ge", "same as >="),
    ("and", "same as &&"), ("or", "same as ||"), ("not", "same as !"),
]


def help_catalog() -> Dict[str, Any]:
    return {
        "functions": [{"name": n, "signature": HELP[n][0], "description": HELP[n][1], "returns": HELP[n][2], "example": HELP[n][3],
                       "min_args": FUNCTIONS[n][0], "max_args": FUNCTIONS[n][1]} for n in FUNCTIONS],
        "operators": [{"token": t, "description": d} for t, d in OPERATORS_HELP],
    }


# ---- evaluation --------------------------------------------------------------------------

def _compare(op: str, a: Any, b: Any) -> bool:
    if op == "==":
        return a == b
    if op == "!=":
        return a != b
    if a is None or b is None or isinstance(a, bool) or isinstance(b, bool):
        return False
    if isinstance(a, (int, float)) != isinstance(b, (int, float)):
        return False
    return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]


def evaluate(ast, lookup: Callable[[str], Any]) -> Any:
    def ev(n):
        k = n[0]
        if k == "lit":
            return n[1]
        if k == "attr":
            return lookup(n[1])
        if k == "not":
            return not _truthy(ev(n[1]))
        if k == "and":
            return _truthy(ev(n[1])) and _truthy(ev(n[2]))
        if k == "or":
            return _truthy(ev(n[1])) or _truthy(ev(n[2]))
        if k == "cmp":
            return _compare(n[1], ev(n[2]), ev(n[3]))
        if k == "if":
            return ev(n[2]) if _truthy(ev(n[1])) else ev(n[3])
        if k == "call":
            return FUNCTIONS[n[1]][2](*[ev(a) for a in n[2]])
        raise ElError("invalid expression")

    return ev(ast)


def _truthy(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    raise ElError("a condition must be true or false")


def matches(ast, lookup: Callable[[str], Any]) -> bool:
    """False on any evaluation problem: a rule must never grant membership by accident."""
    try:
        return evaluate(ast, lookup) is True
    except ElError:
        return False


_BOOL_FUNCS = {"String.stringContains", "Arrays.isEmpty", "Arrays.contains"}


def is_boolean(n) -> bool:
    """Static check that the whole expression yields true/false (so a typo like `user.department` is caught on save)."""
    k = n[0]
    if k in ("and", "or", "not", "cmp"):
        return True
    if k == "lit":
        return isinstance(n[1], bool)
    if k == "call":
        return n[1] in _BOOL_FUNCS
    if k == "if":
        return is_boolean(n[2]) and is_boolean(n[3])
    return False
