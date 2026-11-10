"""SCIM-style list standard for admin collections (ADR 025).

Query: startIndex (1-based), count (default 25, max 100, 0 = totals only), sortBy, sortOrder (ascending|descending), filter (SCIM grammar).
Reply: {"totalResults", "startIndex", "itemsPerPage", "Resources"}.
Sort and filter attributes come only from per-collection allow-lists, keyed by lower-case response field name.
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence

from fastapi import HTTPException, Query
from sqlalchemy import String, func

from backend.app.scim import filter as flt
from backend.app.scim.errors import ScimError

DEFAULT_COUNT = 25
MAX_COUNT = 100
MAX_START = 1_000_000


@dataclass
class ListParams:
    start_index: int = 1
    count: int = DEFAULT_COUNT
    sort_by: Optional[str] = None
    descending: bool = False
    filter: Optional[str] = None


def list_params(
    startIndex: int = Query(1, description="1-based index of the first result"),
    count: int = Query(DEFAULT_COUNT, description="Results per page (max 100; 0 returns only totalResults)"),
    sortBy: Optional[str] = Query(None, max_length=64),
    sortOrder: Optional[str] = Query(None, max_length=16),
    filter: Optional[str] = Query(None, max_length=flt.MAX_LENGTH, description="SCIM filter expression"),
) -> ListParams:
    """FastAPI dependency. Out-of-range numbers are clamped (like SCIM); a bad sortOrder is a 400."""
    if sortOrder is not None and sortOrder.lower() not in ("ascending", "descending"):
        raise HTTPException(status_code=400, detail="sortOrder must be ascending or descending")
    return ListParams(
        start_index=min(max(startIndex, 1), MAX_START),
        count=min(max(count, 0), MAX_COUNT),
        sort_by=sortBy.strip().lower() if sortBy and sortBy.strip() else None,
        descending=(sortOrder or "").lower() == "descending",
        filter=filter if filter and filter.strip() else None,
    )


def envelope(resources: list, total: int, p: ListParams) -> dict:
    return {"totalResults": total, "startIndex": p.start_index, "itemsPerPage": len(resources), "Resources": resources}


def _bad(detail: str) -> HTTPException:
    return HTTPException(status_code=400, detail=detail)


def apply_filter(query, p: ListParams, attrs: Optional[Dict[str, "flt.Attr"]]):
    if p.filter is None:
        return query
    if not attrs:
        raise _bad("Filtering is not supported on this collection")
    try:
        return query.filter(flt.build(p.filter, attrs))
    except ScimError as e:
        raise _bad(e.detail)


def order_clauses(p: ListParams, sort: Dict[str, Any], default_order: Sequence[Any], tiebreak: Any) -> list:
    """ORDER BY: the requested sort (strings case-insensitive, nulls last) then the primary key, so paging is stable."""
    if not p.sort_by:
        return list(default_order)
    col = sort.get(p.sort_by)
    if col is None:
        raise _bad(f"Cannot sort by '{p.sort_by[:60]}'")
    if isinstance(getattr(col, "type", None), String):
        col = func.lower(col)
    d = (lambda c: c.desc()) if p.descending else (lambda c: c.asc())
    return [d(col).nulls_last(), d(tiebreak)]


def paginate(query, p: ListParams, *, sort: Dict[str, Any], default_order: Sequence[Any], tiebreak: Any,
             filter_attrs: Optional[Dict[str, "flt.Attr"]] = None, render: Callable[[list], list] = list) -> dict:
    query = apply_filter(query, p, filter_attrs)
    order = order_clauses(p, sort, default_order, tiebreak)
    total = query.count()
    rows = query.order_by(*order).offset(p.start_index - 1).limit(p.count).all() if p.count else []
    return envelope(render(rows), total, p)


def sortable(attrs: Dict[str, "flt.Attr"], **extra: Any) -> Dict[str, Any]:
    """Sort allow-list derived from the filter attributes (columns only), plus extras such as the primary key."""
    out = {k: a.expr for k, a in attrs.items() if a.expr is not None and a.kind in ("str", "date")}
    out.update(extra)
    return out


def paginate_list(items: List[dict], p: ListParams, *, sort: Dict[str, Callable[[dict], Any]], default_key: Optional[Callable[[dict], Any]] = None) -> dict:
    """The same contract for collections assembled in Python (rows that need per-row computation before they can be filtered).
    Filter expressions are not available here; `sort` maps attribute name -> key function."""
    if p.filter is not None:
        raise _bad("Filtering is not supported on this collection")
    if p.sort_by:
        key = sort.get(p.sort_by)
        if key is None:
            raise _bad(f"Cannot sort by '{p.sort_by[:60]}'")
        # missing values last in both directions; strings case-insensitive
        def k(x):
            v = key(x)
            return (v is None, v.lower() if isinstance(v, str) else v)
        present = [x for x in items if key(x) is not None]
        missing = [x for x in items if key(x) is None]
        present.sort(key=k, reverse=p.descending)
        items = present + missing
    elif default_key is not None:
        items = sorted(items, key=default_key)
    page = items[p.start_index - 1:p.start_index - 1 + p.count] if p.count else []
    return envelope(page, len(items), p)
