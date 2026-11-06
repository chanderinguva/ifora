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
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import declared_attr, with_loader_criteria

from backend.app.db import Base

DEFAULT_TENANT_SLUG = "default"


class TenantContextMissing(RuntimeError):
    """A tenant-owned table was touched without a tenant context."""


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
    return {m.local_table.name for m in Base.registry.mappers if issubclass(m.class_, TenantOwned)}


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
    state.statement = state.statement.options(
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
