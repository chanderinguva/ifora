"""Lookup tables (ADR 021 section 2): typed columns, optional unique key, reads and writes shared by the admin API and
the recipe steps.

Trust model. A table is either *admin-managed* (default: only administrators write it, so what a recipe reads from it is
as trustworthy as the table) or *recipe-writable* (recipes may add, upsert and delete rows with any data, including text
users typed themselves, so everything read back from it is treated like user-editable text: see definition.taint_checker).
"""

import json
import math
import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.app.recipes import templates as tpl
from backend.app.recipes.models import LookupRow, LookupTable

NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
TYPES = ("text", "number", "boolean", "date")
MAX_COLUMNS = 20
MAX_ROWS = 50_000
MAX_TABLES = 50
MAX_TEXT = 500
MAX_ROW_BYTES = 4096
MAX_IMPORT_ROWS = 5000
MAX_DELETE_MATCHES = 100


class LookupError_(ValueError):
    """Bad table definition, row or value. The message is safe to show to admins."""


# ---- definitions ---------------------------------------------------------------------------------------------

def normalise_columns(columns: Any) -> List[Dict[str, str]]:
    if not isinstance(columns, list) or not columns:
        raise LookupError_("a table needs at least one column")
    if len(columns) > MAX_COLUMNS:
        raise LookupError_(f"at most {MAX_COLUMNS} columns")
    out, seen = [], set()
    for c in columns:
        if not isinstance(c, dict) or set(c) - {"name", "type"}:
            raise LookupError_("each column needs a name and a type")
        name, typ = c.get("name"), c.get("type", "text")
        if not isinstance(name, str) or not NAME.match(name):
            raise LookupError_("column names look like department or cost_centre (lowercase letters, digits, _; start with a letter)")
        if typ not in TYPES:
            raise LookupError_(f"column '{name}': type must be one of {', '.join(TYPES)}")
        if name in seen:
            raise LookupError_(f"duplicate column '{name}'")
        seen.add(name)
        out.append({"name": name, "type": typ})
    return out


def column_types(table: LookupTable) -> Dict[str, str]:
    return {c["name"]: c["type"] for c in table.columns}


# ---- values --------------------------------------------------------------------------------------------------

def coerce(value: Any, typ: str, column: str = "") -> Any:
    """Convert a value (usually rendered text) to the column's type. None and, for non-text columns, "" mean no value."""
    where = f"column '{column}': " if column else ""
    if value is None or (value == "" and typ != "text"):
        return None
    if typ == "text":
        t = tpl.to_text(value)
        if len(t) > MAX_TEXT:
            raise LookupError_(f"{where}text is longer than {MAX_TEXT} characters")
        return t
    if typ == "number":
        if isinstance(value, bool):
            raise LookupError_(f"{where}'{value}' is not a number")
        try:
            n = float(value) if not isinstance(value, (int, float)) else value
        except (TypeError, ValueError):
            raise LookupError_(f"{where}'{str(value)[:40]}' is not a number")
        if isinstance(n, float) and (math.isnan(n) or math.isinf(n)):
            raise LookupError_(f"{where}'{str(value)[:40]}' is not a number")
        if abs(n) > 1e15:
            raise LookupError_(f"{where}number is too large")
        return int(n) if float(n).is_integer() else n
    if typ == "boolean":
        if isinstance(value, bool):
            return value
        v = str(value).strip().lower()
        if v in ("true", "yes", "1"):
            return True
        if v in ("false", "no", "0"):
            return False
        raise LookupError_(f"{where}'{str(value)[:40]}' is not true or false")
    if typ == "date":
        try:
            return date.fromisoformat(str(value).strip()).isoformat()
        except ValueError:
            raise LookupError_(f"{where}'{str(value)[:40]}' is not a date (use YYYY-MM-DD)")
    raise LookupError_(f"unknown column type '{typ}'")


def coerce_row(table: LookupTable, values: Dict[str, Any], *, complete: bool = True) -> Dict[str, Any]:
    """Validate and convert a row. With complete=True every column is present (missing ones are None)."""
    if not isinstance(values, dict):
        raise LookupError_("a row is a set of column values")
    types = column_types(table)
    unknown = [k for k in values if k not in types]
    if unknown:
        raise LookupError_(f"unknown column '{unknown[0]}'")
    out = {c: coerce(values.get(c), t, c) for c, t in types.items() if complete or c in values}
    if len(json.dumps(out)) > MAX_ROW_BYTES:
        raise LookupError_("the row is too large")
    if table.key_column and (complete or table.key_column in out) and out.get(table.key_column) in (None, ""):
        raise LookupError_(f"column '{table.key_column}' is the key and cannot be empty")
    return out


def key_text(value: Any) -> str:
    return tpl.to_text(value)[:500]


# ---- reads ---------------------------------------------------------------------------------------------------

def get_table(db: Session, name: str) -> Optional[LookupTable]:
    return db.query(LookupTable).filter(LookupTable.name == name).first()


def _match(db: Session, table: LookupTable, column: str, value: Any):
    typ = column_types(table).get(column)
    if typ is None:
        raise LookupError_(f"the table '{table.name}' has no column '{column}'")
    v = coerce(value, typ, column)
    q = db.query(LookupRow).filter(LookupRow.table_id == table.id)
    if v is None:
        return q.filter(LookupRow.id < 0)   # an empty value matches nothing (not "rows with an empty cell")
    if column == table.key_column:
        return q.filter(LookupRow.key_value == key_text(v))
    return q.filter(LookupRow.data.contains({column: v}))


def read(db: Session, table: LookupTable, column: str, value: Any) -> Tuple[int, Dict[str, Any]]:
    """(how many rows match, the first match by creation order or {})."""
    q = _match(db, table, column, value)
    n = q.count()
    row = q.order_by(LookupRow.id).first() if n else None
    return n, ({c["name"]: row.data.get(c["name"]) for c in table.columns} if row else {})   # columns added later read as empty


# ---- writes (callers hold no lock; this takes the table row lock itself) -------------------------------------

def _lock(db: Session, table: LookupTable) -> LookupTable:
    return db.query(LookupTable).filter(LookupTable.id == table.id).with_for_update().one()


def add_row(db: Session, table: LookupTable, values: Dict[str, Any]) -> LookupRow:
    table = _lock(db, table)
    if table.row_count >= MAX_ROWS:
        raise LookupError_(f"a table holds at most {MAX_ROWS} rows")
    data = coerce_row(table, values)
    kv = key_text(data[table.key_column]) if table.key_column else None
    if kv is not None and db.query(LookupRow.id).filter(LookupRow.table_id == table.id, LookupRow.key_value == kv).first():
        raise LookupError_(f"a row with {table.key_column} = '{kv}' already exists")
    row = LookupRow(table_id=table.id, data=data, key_value=kv)
    db.add(row)
    table.row_count += 1
    table.updated_at = func.now()
    db.flush()
    return row


def upsert_row(db: Session, table: LookupTable, values: Dict[str, Any]) -> str:
    """Insert, or update the row with the same key. Returns 'inserted' or 'updated'."""
    if not table.key_column:
        raise LookupError_(f"the table '{table.name}' has no key column, so rows cannot be updated by key")
    table = _lock(db, table)
    data = coerce_row(table, values, complete=False)
    if data.get(table.key_column) is None:
        raise LookupError_(f"a value for the key column '{table.key_column}' is required")
    kv = key_text(data[table.key_column])
    row = db.query(LookupRow).filter(LookupRow.table_id == table.id, LookupRow.key_value == kv).first()
    if row is None:
        add_row(db, table, values)
        return "inserted"
    merged = {**row.data, **data}
    if len(json.dumps(merged)) > MAX_ROW_BYTES:
        raise LookupError_("the row is too large")
    row.data = merged
    table.updated_at = func.now()
    db.flush()
    return "updated"


def delete_by_key(db: Session, table: LookupTable, key: Any) -> str:
    if not table.key_column:
        raise LookupError_(f"the table '{table.name}' has no key column, so rows cannot be deleted by key")
    table = _lock(db, table)
    typ = column_types(table)[table.key_column]
    v = coerce(key, typ, table.key_column)
    if v is None:
        raise LookupError_("a key value is required")
    n = db.query(LookupRow).filter(LookupRow.table_id == table.id, LookupRow.key_value == key_text(v)).delete(synchronize_session=False)
    table.row_count = max(table.row_count - n, 0)
    table.updated_at = func.now()
    db.flush()
    return "deleted" if n else "not_found"


# ---- which recipe steps read untrusted data ------------------------------------------------------------------

def steps_of(steps: List[dict]):
    for s in steps or []:
        yield s
        yield from steps_of(s.get("then") or [])
        yield from steps_of(s.get("else") or [])


def tables_used(definition: dict) -> set:
    return {s["config"]["table"] for part in ("steps", "on_error") for s in steps_of(definition.get(part) or [])
            if s.get("type") in ("lookup_row", "lookup_write") and isinstance(s.get("config"), dict) and "table" in s["config"]}


def tainted_step_ids(db: Session, definition: dict) -> set:
    """Ids of the lookup steps that read from a recipe-writable (or missing) table: their outputs count as user-editable."""
    ids = set()
    cache: Dict[str, bool] = {}
    for part in ("steps", "on_error"):
        for s in steps_of(definition.get(part) or []):
            if s.get("type") != "lookup_row":
                continue
            name = s["config"]["table"]
            if name not in cache:
                t = get_table(db, name)
                cache[name] = t is None or not t.admin_managed
            if cache[name]:
                ids.add(s["id"])
    return ids
