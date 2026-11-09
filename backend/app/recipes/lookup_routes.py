"""Admin API for lookup tables (ADR 021 section 2): tables, rows, CSV import and export. Area: automation."""

import csv
import io
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import String, cast, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.auth.deps import require_admin
from backend.app.config import settings
from backend.app.db import get_db
from backend.app.recipes import lookup
from backend.app.recipes.models import LookupRow, LookupTable, Recipe, RecipeVersion
from backend.app.users.model import User


def _enabled():
    if not settings.RECIPES_ENABLED:
        raise HTTPException(status_code=404, detail="Recipes are not enabled")


router = APIRouter(prefix="/admin/lookup-tables", tags=["lookup-tables"], dependencies=[Depends(_enabled)])
MAX_CSV_BYTES = 1_000_000


class TableBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=40)
    description: Optional[str] = Field(None, max_length=300)
    columns: List[Dict[str, Any]]
    key_column: Optional[str] = Field(None, max_length=40)
    admin_managed: bool = True


class TableUpdate(BaseModel):
    description: Optional[str] = Field(None, max_length=300)
    admin_managed: Optional[bool] = None
    add_columns: Optional[List[Dict[str, Any]]] = None


class RowBody(BaseModel):
    values: Dict[str, Any]


class ImportBody(BaseModel):
    csv: str = Field(..., max_length=MAX_CSV_BYTES)
    mode: str = Field("append", pattern="^(append|replace)$")


def _bad(e: Exception, code: int = 422):
    return HTTPException(status_code=code, detail=str(e))


def _used_by(db: Session, name: str) -> List[str]:
    """Recipes whose draft or published version has a step using the table."""
    out = []
    for r in db.query(Recipe).order_by(Recipe.id).all():
        defs = [r.draft or {}]
        if r.published_version:
            v = db.query(RecipeVersion).filter(RecipeVersion.recipe_id == r.id, RecipeVersion.version == r.published_version).first()
            if v:
                defs.append(v.definition or {})
        if any(name in lookup.tables_used(d) for d in defs):
            out.append(r.name)
    return out


def _dict(t: LookupTable, db: Optional[Session] = None) -> dict:
    d = {"id": t.id, "name": t.name, "description": t.description, "columns": t.columns, "key_column": t.key_column,
         "admin_managed": t.admin_managed, "row_count": t.row_count,
         "created_at": t.created_at.isoformat() if t.created_at else None, "updated_at": t.updated_at.isoformat() if t.updated_at else None}
    if db is not None:
        d["used_by"] = _used_by(db, t.name)
    return d


def _table(db: Session, tid: int) -> LookupTable:
    t = db.get(LookupTable, tid)
    if t is None:
        raise HTTPException(status_code=404, detail="Lookup table not found")
    return t


def _row_dict(r: LookupRow) -> dict:
    return {"id": r.id, "values": r.data}


@router.get("")
def list_tables(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return {"items": [_dict(t) for t in db.query(LookupTable).order_by(LookupTable.name).all()],
            "limits": {"max_columns": lookup.MAX_COLUMNS, "max_rows": lookup.MAX_ROWS, "max_tables": lookup.MAX_TABLES, "types": list(lookup.TYPES)}}


@router.post("", status_code=201)
def create_table(body: TableBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    name = body.name.strip()
    if not lookup.NAME.match(name):
        raise HTTPException(status_code=422, detail="the name looks like cost_centres (lowercase letters, digits, _; start with a letter)")
    try:
        cols = lookup.normalise_columns(body.columns)
    except lookup.LookupError_ as e:
        raise _bad(e)
    if body.key_column is not None and body.key_column not in {c["name"] for c in cols}:
        raise HTTPException(status_code=422, detail="the key must be one of the columns")
    if db.query(func.count(LookupTable.id)).scalar() >= lookup.MAX_TABLES:
        raise HTTPException(status_code=422, detail=f"at most {lookup.MAX_TABLES} lookup tables")
    t = LookupTable(name=name, description=(body.description or "").strip() or None, columns=cols, key_column=body.key_column,
                    admin_managed=body.admin_managed, created_by=actor.id)
    db.add(t)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A lookup table with that name already exists")
    record(db, AuditAction.LOOKUP_TABLE_CREATED, request, actor, t.id, "lookup_table",
           {"name": t.name, "columns": [c["name"] for c in cols], "key": t.key_column, "admin_managed": t.admin_managed})
    db.commit()
    return _dict(t, db)


@router.get("/{tid}")
def get_table(tid: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return _dict(_table(db, tid), db)


@router.put("/{tid}")
def update_table(tid: int, body: TableUpdate, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    t = _table(db, tid)
    meta: Dict[str, Any] = {"name": t.name}
    if body.description is not None:
        t.description = body.description.strip() or None
    if body.admin_managed is not None and body.admin_managed != t.admin_managed:
        # recipes that read the table in decisions or state changes were checked under the old trust level; the engine
        # re-checks at run time, so those steps fail rather than act on data they should not trust
        meta.update(admin_managed=body.admin_managed, used_by=_used_by(db, t.name))
        t.admin_managed = body.admin_managed
    if body.add_columns:
        try:
            extra = lookup.normalise_columns(body.add_columns)
            merged = lookup.normalise_columns([*t.columns, *extra])
        except lookup.LookupError_ as e:
            raise _bad(e)
        t.columns = merged
        meta["added_columns"] = [c["name"] for c in extra]
    t.updated_at = func.now()
    record(db, AuditAction.LOOKUP_TABLE_UPDATED, request, actor, t.id, "lookup_table", meta)
    db.commit()
    return _dict(t, db)


@router.delete("/{tid}")
def delete_table(tid: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    t = _table(db, tid)
    used = _used_by(db, t.name)
    if used:
        raise HTTPException(status_code=409, detail="Used by recipes: " + ", ".join(used[:5]) + ". Remove the lookup steps first.")
    record(db, AuditAction.LOOKUP_TABLE_DELETED, request, actor, t.id, "lookup_table", {"name": t.name, "rows": t.row_count})
    db.delete(t)
    db.commit()
    return {"ok": True}


# ---- rows --------------------------------------------------------------------------------------------------------

@router.get("/{tid}/rows")
def list_rows(tid: int, q: Optional[str] = Query(None, max_length=100), limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0, le=100_000),
              db: Session = Depends(get_db), _: User = Depends(require_admin)):
    t = _table(db, tid)
    query = db.query(LookupRow).filter(LookupRow.table_id == t.id)
    if q:
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.filter(cast(LookupRow.data, String).ilike(like, escape="\\"))
    total = query.count()
    rows = query.order_by(LookupRow.id).offset(offset).limit(limit).all()
    return {"items": [_row_dict(r) for r in rows], "total": total, "limit": limit, "offset": offset}


@router.post("/{tid}/rows", status_code=201)
def add_row(tid: int, body: RowBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    t = _table(db, tid)
    try:
        row = lookup.add_row(db, t, body.values)
    except lookup.LookupError_ as e:
        db.rollback()
        raise _bad(e)
    record(db, AuditAction.LOOKUP_ROWS_CHANGED, request, actor, t.id, "lookup_table", {"name": t.name, "op": "add", "row_id": row.id, "key": row.key_value})
    db.commit()
    return _row_dict(row)


@router.put("/{tid}/rows/{rid}")
def update_row(tid: int, rid: int, body: RowBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    t = _table(db, tid)
    row = db.query(LookupRow).filter(LookupRow.id == rid, LookupRow.table_id == t.id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Row not found")
    try:
        data = lookup.coerce_row(t, body.values)
        kv = lookup.key_text(data[t.key_column]) if t.key_column else None
        if kv is not None and db.query(LookupRow.id).filter(LookupRow.table_id == t.id, LookupRow.key_value == kv, LookupRow.id != rid).first():
            raise lookup.LookupError_(f"a row with {t.key_column} = '{kv}' already exists")
    except lookup.LookupError_ as e:
        raise _bad(e)
    row.data, row.key_value = data, kv
    t.updated_at = func.now()
    record(db, AuditAction.LOOKUP_ROWS_CHANGED, request, actor, t.id, "lookup_table", {"name": t.name, "op": "update", "row_id": rid, "key": kv})
    db.commit()
    return _row_dict(row)


@router.delete("/{tid}/rows/{rid}")
def delete_row(tid: int, rid: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    t = lookup._lock(db, _table(db, tid))
    row = db.query(LookupRow).filter(LookupRow.id == rid, LookupRow.table_id == t.id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Row not found")
    record(db, AuditAction.LOOKUP_ROWS_CHANGED, request, actor, t.id, "lookup_table", {"name": t.name, "op": "delete", "row_id": rid, "key": row.key_value})
    db.delete(row)
    t.row_count = max(t.row_count - 1, 0)
    db.commit()
    return {"ok": True}


# ---- CSV ---------------------------------------------------------------------------------------------------------

def _csv_cell(v: Any) -> str:
    """Neutralise spreadsheet formula injection (rows can hold text recipes copied from users)."""
    t = "" if v is None else str(v).lower() if isinstance(v, bool) else str(v)
    return "'" + t if t[:1] in ("=", "+", "-", "@", "\t", "\r") else t


@router.get("/{tid}/export")
def export_rows(tid: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    t = _table(db, tid)
    names = [c["name"] for c in t.columns]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(names)
    for r in db.query(LookupRow).filter(LookupRow.table_id == t.id).order_by(LookupRow.id).limit(lookup.MAX_ROWS):
        w.writerow([_csv_cell(r.data.get(n)) for n in names])
    record(db, AuditAction.LOOKUP_ROWS_EXPORTED, request, actor, t.id, "lookup_table", {"name": t.name, "rows": t.row_count})
    db.commit()
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="{t.name}.csv"', "Cache-Control": "no-store"})


@router.post("/{tid}/import")
def import_rows(tid: int, body: ImportBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    """All or nothing: the first problems are listed with their line numbers and nothing is written."""
    t = lookup._lock(db, _table(db, tid))
    try:
        rows = list(csv.reader(io.StringIO(body.csv)))
    except csv.Error:
        raise HTTPException(status_code=422, detail="The file is not valid CSV")
    if not rows:
        raise HTTPException(status_code=422, detail="The file is empty")
    header, data_rows = [h.strip() for h in rows[0]], rows[1:]
    names = [c["name"] for c in t.columns]
    if sorted(header) != sorted(names) or len(set(header)) != len(header):
        raise HTTPException(status_code=422, detail="The first line must name exactly these columns: " + ", ".join(names))
    if len(data_rows) > lookup.MAX_IMPORT_ROWS:
        raise HTTPException(status_code=422, detail=f"At most {lookup.MAX_IMPORT_ROWS} rows per import")
    existing = 0 if body.mode == "replace" else t.row_count
    if existing + len(data_rows) > lookup.MAX_ROWS:
        raise HTTPException(status_code=422, detail=f"A table holds at most {lookup.MAX_ROWS} rows")
    prepared, errors, keys = [], [], set()
    if body.mode == "append" and t.key_column:
        keys = {r[0] for r in db.query(LookupRow.key_value).filter(LookupRow.table_id == t.id)}
    for i, cells in enumerate(data_rows, start=2):
        if not any(c.strip() for c in cells):
            continue
        if len(cells) != len(header):
            errors.append(f"line {i}: expected {len(header)} values, found {len(cells)}")
            continue
        try:
            d = lookup.coerce_row(t, dict(zip(header, cells)))
            kv = lookup.key_text(d[t.key_column]) if t.key_column else None
            if kv is not None:
                if kv in keys:
                    raise lookup.LookupError_(f"duplicate key '{kv}'")
                keys.add(kv)
            prepared.append((d, kv))
        except lookup.LookupError_ as e:
            errors.append(f"line {i}: {e}")
        if len(errors) >= 5:
            break
    if errors:
        raise HTTPException(status_code=422, detail="Nothing was imported. " + "; ".join(errors))
    if body.mode == "replace":
        db.query(LookupRow).filter(LookupRow.table_id == t.id).delete(synchronize_session=False)
        t.row_count = 0
    db.add_all([LookupRow(table_id=t.id, data=d, key_value=kv) for d, kv in prepared])
    t.row_count += len(prepared)
    t.updated_at = func.now()
    record(db, AuditAction.LOOKUP_ROWS_CHANGED, request, actor, t.id, "lookup_table", {"name": t.name, "op": "import", "mode": body.mode, "rows": len(prepared)})
    db.commit()
    return {"imported": len(prepared), "row_count": t.row_count}
