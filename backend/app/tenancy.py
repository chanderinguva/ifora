"""Tenant-aware data model (ADR 005, D5).

The product ships single-tenant, but every tenant-owned row carries a tenant_id and every ORM
query/flush is scoped to the session's tenant, so a later multi-tenant release does not require
retrofitting authorization queries.

Rules enforced here (fail closed):
- A Session must have a tenant context (``session.info["tenant_id"]``) before it SELECTs/UPDATEs/DELETEs
  tenant-owned rows. Missing context raises ``TenantContextMissing``; there is no implicit "all tenants".
- New tenant-owned rows get the session's tenant_id; setting a different tenant_id raises.
- Cross-tenant work (migrations, a future platform operator) must opt in explicitly with
  ``unscoped(session)``.
"""

from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Table, event
from sqlalchemy.sql import visitors
from sqlalchemy import Delete, Select, Update
from sqlalchemy.sql.dml import Insert
from sqlalchemy.sql.selectable import Alias, Join
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import declared_attr, with_loader_criteria

from backend.app.db import Base

DEFAULT_TENANT_SLUG = "default"


class TenantContextMissing(RuntimeError):
    """A tenant-owned table was touched without a tenant context."""


class UnscopedStatement(RuntimeError):
    """A Core statement touched a tenant table without a tenant condition (IFORA-18)."""


class CrossTenantWrite(RuntimeError):
    """An object belonging to another tenant was added to this session."""


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, autoincrement=True)
    slug = Column(String(63), nullable=False, unique=True)
    name = Column(String(255), nullable=False)
    status = Column(String(20), nullable=False, default="active", server_default="active")
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class TenantOwned:
    """Mixin for every table whose rows belong to a tenant."""

    @declared_attr
    def tenant_id(cls):  # noqa: N805
        return Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)


def use_tenant(session: OrmSession, tenant_id: int) -> OrmSession:
    session.info["tenant_id"] = tenant_id
    session.info.pop("unscoped", None)
    return session


@contextmanager
def unscoped(session: OrmSession):
    """Explicit, greppable opt-out for cross-tenant maintenance code. Not used by request handlers."""
    prev = session.info.get("unscoped")
    session.info["unscoped"] = True
    try:
        yield session
    finally:
        if prev is None:
            session.info.pop("unscoped", None)
        else:
            session.info["unscoped"] = prev


_default_tenant_id: int | None = None


def default_tenant_id(session_factory=None) -> int:
    """Single-tenant resolution: the seeded default tenant (cached per process)."""
    global _default_tenant_id
    if _default_tenant_id is None:
        from backend.app.db import SessionLocal

        s = (session_factory or SessionLocal)()
        try:
            with unscoped(s):
                row = s.query(Tenant.id).filter(Tenant.slug == DEFAULT_TENANT_SLUG).first()
            if row is None:
                raise RuntimeError("default tenant missing; run migrations")
            _default_tenant_id = row[0]
        finally:
            s.close()
    return _default_tenant_id


def reset_tenant_cache() -> None:
    global _default_tenant_id
    _default_tenant_id = None


def tenant_session(tenant_id: int | None = None) -> OrmSession:
    """New session bound to a tenant (default tenant while single-tenant)."""
    from backend.app.db import SessionLocal

    s = SessionLocal()
    return use_tenant(s, tenant_id if tenant_id is not None else default_tenant_id())


def _tenant_tables() -> set:
    return {m.local_table.name for m in Base.registry.mappers if issubclass(m.class_, TenantOwned)} | _core_tenant_tables()


def _core_tenant_tables() -> set:
    """Plain Tables that carry tenant_id but have no mapped class (e.g. user_group_membership). The ORM loader
    criteria cannot scope these, so Core statements on them must name the tenant themselves."""
    mapped = {m.local_table.name for m in Base.registry.mappers}
    return {t.name for t in Base.metadata.tables.values() if "tenant_id" in t.c and t.name not in mapped}


def _direct_tables(frm):
    """Core tenant tables (or aliases of them) read directly by a FROM item, looking through joins only."""
    core = _core_tenant_tables()
    if isinstance(frm, Join):
        return _direct_tables(frm.left) + _direct_tables(frm.right)
    base = frm.element if isinstance(frm, Alias) else frm
    return [frm] if isinstance(base, Table) and base.name in core else []


def _scope_core(stmt, tid: int):
    """Add `tenant_id = :tid` to every Core SELECT/UPDATE/DELETE over an unmapped tenant table.

    ORM loader criteria cannot scope plain Tables such as user_group_membership, so without this a Core statement
    would read or change every tenant's rows. Each SELECT in the statement (subqueries included) gets the
    condition for the tables it reads directly; UPDATE/DELETE get it for their target. INSERTs are filled and
    checked by the database trigger (migration 0030). Fails closed on a shape it cannot rewrite.
    """
    if isinstance(stmt, Insert) or not _core_tenant_tables():
        return stmt
    core = _core_tenant_tables()
    if not any(isinstance(e, Table) and e.name in core for e in visitors.iterate(stmt)):
        return stmt

    def on_select(sel):
        extra = tuple(t.c.tenant_id == tid for f in sel.get_final_froms() for t in _direct_tables(f))
        if extra:
            sel._where_criteria = sel._where_criteria + extra

    # Loader-criteria options (already on lazy-load and propagated statements) cannot be cloned: set them aside.
    opts = getattr(stmt, "_with_options", ())
    if opts:
        stmt = stmt._clone()
        stmt._with_options = ()
    out = visitors.cloned_traverse(stmt, {}, {"select": on_select})
    if opts:
        out._with_options = opts
    if isinstance(out, (Update, Delete)) and out.table.name in core:
        out = out.where(out.table.c.tenant_id == tid)
    elif not isinstance(out, (Select, Update, Delete)):
        raise UnscopedStatement(f"cannot scope a {type(stmt).__name__} on a tenant table")
    return out


def _touches_tenant_tables(stmt) -> bool:
    """True if the statement references a tenant-owned table anywhere (columns, FROM, joins, subqueries).

    Walks the whole expression tree: `state.all_mappers` misses `select_from()`-only references, which
    let `query(Model).count()` read every tenant.
    """
    tables = _tenant_tables()
    return any(isinstance(e, Table) and e.name in tables for e in visitors.iterate(stmt))


@event.listens_for(OrmSession, "do_orm_execute")
def _scope_queries(state):
    info = state.session.info
    if info.get("unscoped"):
        return
    tid = info.get("tenant_id")
    if tid is None:
        if _touches_tenant_tables(state.statement):
            raise TenantContextMissing("tenant-owned table accessed without a tenant context")
        return
    state.statement = _scope_core(state.statement, tid).options(
        with_loader_criteria(
            TenantOwned,
            lambda cls: cls.tenant_id == tid,
            include_aliases=True,
            propagate_to_loaders=True,
        )
    )


@event.listens_for(OrmSession, "before_flush")
def _stamp_and_check(session, flush_context, instances):
    if session.info.get("unscoped"):
        return
    tid = session.info.get("tenant_id")
    for obj in session.new:
        if not isinstance(obj, TenantOwned):
            continue
        if obj.tenant_id is None:
            if tid is None:
                raise TenantContextMissing(f"cannot create {type(obj).__name__} without a tenant context")
            obj.tenant_id = tid
        elif tid is not None and obj.tenant_id != tid:
            raise CrossTenantWrite(f"{type(obj).__name__} belongs to tenant {obj.tenant_id}, session is {tid}")
    for obj in session.dirty:
        if isinstance(obj, TenantOwned) and tid is not None and obj.tenant_id != tid:
            raise CrossTenantWrite(f"{type(obj).__name__} belongs to tenant {obj.tenant_id}, session is {tid}")


class TenantNotResolved(RuntimeError):
    """Multi-tenant mode and the request does not name a known, active tenant."""


def resolve_tenant_id(host: str | None) -> int:
    """Tenant for a request. Only the Host header is used (set by the edge); no client-supplied tenant header is read.

    single: the default tenant. host: `<slug>.<TENANT_BASE_DOMAIN>`; anything else raises TenantNotResolved.
    """
    from backend.app.config import settings

    if settings.TENANT_RESOLUTION == "single":
        return default_tenant_id()
    base = settings.TENANT_BASE_DOMAIN.strip().lower().strip(".")
    name = (host or "").split(":")[0].strip().lower().rstrip(".")
    if not base or not name.endswith("." + base):
        raise TenantNotResolved("host does not name a tenant")
    slug = name[: -len(base) - 1]
    if not slug or "." in slug:
        raise TenantNotResolved("host does not name a tenant")
    from backend.app.db import SessionLocal

    s = SessionLocal()
    try:
        with unscoped(s):
            row = s.query(Tenant.id).filter(Tenant.slug == slug, Tenant.status == "active").first()
    finally:
        s.close()
    if row is None:
        raise TenantNotResolved("unknown tenant")
    return row[0]
