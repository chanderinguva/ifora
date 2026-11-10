"""CSV for users: the column set, safe writing (spreadsheet formula injection) and tolerant reading."""

import csv
import io
from typing import Dict, Iterable, List, Tuple

CORE = ["username", "email", "first_name", "last_name"]
GROUPS = "groups"                                            # group names separated by ;
READ_ONLY = ["status", "id", "last_login_at", "created_at"]  # exported for reference, ignored on import
MAX_BYTES = 2_000_000
MAX_ROWS = 500                                               # each row hashes a password, so keep one request bounded
_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(v) -> str:
    """A cell that a spreadsheet would run as a formula is prefixed with ' so it opens as text."""
    s = "" if v is None else str(v)
    return "'" + s if s.startswith(_FORMULA) else s


def write(headers: List[str], rows: Iterable[Dict[str, object]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(headers)
    for r in rows:
        w.writerow([safe_cell(r.get(h)) for h in headers])
    return buf.getvalue()


def unsafe(v: str) -> str:
    """Undo safe_cell, so an exported file re-imports unchanged."""
    return v[1:] if len(v) > 1 and v[0] == "'" and v[1] in _FORMULA else v


def read(text: str) -> Tuple[List[str], List[Dict[str, str]]]:
    """-> (headers, rows). Headers are trimmed and lower-cased; a UTF-8 BOM (Excel) is accepted."""
    if text.startswith("﻿"):
        text = text[1:]
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        header = next(reader)
    except StopIteration:
        raise ValueError("The file is empty")
    except csv.Error as e:
        raise ValueError(f"Not a valid CSV file: {e}")
    headers = [h.strip().lower().replace(" ", "_") for h in header]
    if len(set(headers)) != len(headers) or "" in headers:
        raise ValueError("Header row has a blank or repeated column name")
    rows = []
    try:
        for i, rec in enumerate(reader, start=2):
            if not any(c.strip() for c in rec):
                continue  # blank line
            if len(rec) > len(headers):
                raise ValueError(f"Row {i} has more cells than the header")
            if len(rows) >= MAX_ROWS:
                raise ValueError(f"At most {MAX_ROWS} rows per import; split the file")
            rows.append({h: unsafe(rec[j].strip()) if j < len(rec) else "" for j, h in enumerate(headers)} | {"_line": i})
    except csv.Error as e:
        raise ValueError(f"Not a valid CSV file: {e}")
    return headers, rows
