"""Redaction of secrets from anything stored in job history or returned by the API."""

import re
from typing import Any, Iterable

REDACTED = "[REDACTED]"
_SENSITIVE_KEY = re.compile(r"(authorization|secret|token|passw|api[-_]?key|cookie|signature|credential)", re.I)
MAX_DEPTH = 12


def redact(obj: Any, _depth: int = 0) -> Any:
    """Replace values of sensitive-looking keys (recursively)."""
    if _depth > MAX_DEPTH:
        return REDACTED
    if isinstance(obj, dict):
        return {k: (REDACTED if isinstance(k, str) and _SENSITIVE_KEY.search(k) else redact(v, _depth + 1)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v, _depth + 1) for v in obj]
    return obj


_KV = re.compile(
    r"((?:authorization|secret|token|passw\w*|api[-_]?key|cookie|signature|credential)\w*[\"']?\s*[:=]\s*[\"']?)([^\"'&\s,;}]+)",
    re.I,
)


def redact_text(text: str) -> str:
    """Redact a response body kept in history: structured JSON by key name, anything else by key=value patterns."""
    import json

    try:
        return json.dumps(redact(json.loads(text)))
    except ValueError:
        return _KV.sub(lambda m: m.group(1) + REDACTED, text)


def scrub(obj: Any, secrets: Iterable[str], _depth: int = 0) -> Any:
    """Remove literal secret values wherever they appear in strings (e.g. a remote server echoing a token)."""
    secrets = [s for s in secrets if s]
    if not secrets:
        return obj
    if _depth > MAX_DEPTH:
        return REDACTED
    if isinstance(obj, str):
        for s in secrets:
            obj = obj.replace(s, REDACTED)
        return obj
    if isinstance(obj, dict):
        return {k: scrub(v, secrets, _depth + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub(v, secrets, _depth + 1) for v in obj]
    return obj
