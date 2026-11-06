"""Cross-tenant isolation (ADR 005, D5): every tenant-owned query and write is tenant-scoped, fail closed."""

import pytest
from sqlalchemy.exc import IntegrityError

from backend.app.db import SessionLocal
from backend.app.groups.model import Group
from backend.app.tenancy import (
    CrossTenantWrite,
    Tenant,
    TenantContextMissing,
    tenant_session,
    unscoped,
    use_tenant,
)
from backend.app.users.model import User
from tests.conftest import Api, STRONG, make_user


@pytest.fixture
def tenant_b():
    s = SessionLocal()
    with unscoped(s):
        t = Tenant(slug="acme", name="Acme")
        s.add(t)
        s.commit()
        tid = t.id
    s.close()
    yield tid
    # tenants survive the per-test TRUNCATE (the default tenant must); remove ours after its rows are gone
    from backend.app.db import engine

    with engine.begin() as conn:
        for t in ("users", "groups", "sessions", "audit_events"):
            conn.exec_driver_sql(f"DELETE FROM {t} WHERE tenant_id = %s", (tid,))
        conn.exec_driver_sql("DELETE FROM tenants WHERE id = %s", (tid,))


def b_session(tid):
    return use_tenant(SessionLocal(), tid)


def user_in(tid, email, **kw):
    s = b_session(tid)
    u = make_user(s, email, **kw)
    s.close()
    return u


def test_session_without_tenant_context_fails_closed():
    s = SessionLocal()
    with pytest.raises(TenantContextMissing):
        s.query(User).all()
    with pytest.raises(TenantContextMissing):
        s.add(User(email="x@example.com", username="x", first_name="a", last_name="b", password=STRONG))
        s.flush()
    s.rollback()
    s.close()


def test_queries_only_see_their_own_tenant(db, tenant_b):
    make_user(db, "a@example.com")
    user_in(tenant_b, "b@example.com")
    assert [u.email for u in db.query(User).all()] == ["a@example.com"]
    sb = b_session(tenant_b)
    assert [u.email for u in sb.query(User).all()] == ["b@example.com"]
    assert sb.query(User).filter(User.email == "a@example.com").first() is None
    sb.close()


def test_new_rows_are_stamped_and_cross_tenant_writes_rejected(db, tenant_b):
    u = make_user(db, "a@example.com")
    assert u.tenant_id != tenant_b
    sb = b_session(tenant_b)
    g = Group(name="g")
    sb.add(g)
    sb.commit()
    assert g.tenant_id == tenant_b
    try:
        foreign = User(email="z@example.com", username="z", first_name="a", last_name="b", password=STRONG)
        foreign.tenant_id = u.tenant_id
        sb.add(foreign)
        with pytest.raises(CrossTenantWrite):
            sb.flush()
    finally:
        sb.rollback()
        sb.close()


def test_email_is_unique_per_tenant_not_globally(db, tenant_b):
    make_user(db, "same@example.com")
    user_in(tenant_b, "same@example.com")  # allowed in another tenant
    with pytest.raises(IntegrityError):
        make_user(db, "same@example.com")
    db.rollback()


def test_bulk_delete_cannot_reach_other_tenants(db, tenant_b):
    make_user(db, "a@example.com")
    user_in(tenant_b, "b@example.com")
    assert db.query(User).delete(synchronize_session=False) == 1
    db.commit()
    s = SessionLocal()
    with unscoped(s):
        assert [u.email for u in s.query(User).all()] == ["b@example.com"]
    s.close()


def test_admin_api_cannot_see_or_touch_other_tenant_users(db, tenant_b, super_admin):
    other = user_in(tenant_b, "victim@example.com")
    assert all(u["email"] != "victim@example.com" for u in super_admin.get("/admin/users").json()["items"])
    assert super_admin.get(f"/admin/users/{other.id}").status_code == 404
    assert super_admin.patch(f"/admin/users/{other.id}", {"status": "inactive"}).status_code == 404
    assert super_admin.delete(f"/admin/users/{other.id}").status_code == 404
    assert super_admin.post(f"/admin/users/{other.id}/password", {"new_password": STRONG}).status_code == 404


def test_other_tenant_user_cannot_log_in_here(tenant_b):
    user_in(tenant_b, "victim@example.com")
    assert Api().login("victim@example.com").status_code == 401


def test_audit_log_is_tenant_scoped(db, tenant_b, super_admin):
    s = b_session(tenant_b)
    from backend.app.audit.model import AuditAction, AuditEvent

    s.add(AuditEvent(AuditAction.LOGIN_SUCCESS, details="other-tenant-secret"))
    s.commit()
    s.close()
    body = super_admin.get("/admin/audit").text
    assert "other-tenant-secret" not in body


def test_aggregate_and_subquery_forms_are_scoped_too(db, tenant_b):
    """Regression: count()/select_from() once ignored the tenant filter and read every tenant."""
    from sqlalchemy import func, select

    make_user(db, "a@example.com")
    user_in(tenant_b, "b@example.com")
    assert db.query(User).count() == 1
    assert db.query(func.count(User.id)).scalar() == 1
    assert db.execute(select(func.count()).select_from(User)).scalar() == 1
    assert db.execute(select(func.count()).select_from(select(User).subquery())).scalar() == 1
    assert db.query(User).filter(User.id.in_(select(User.id))).count() == 1


def test_no_context_blocks_aggregates_too():
    from sqlalchemy import func, select

    s = SessionLocal()
    with pytest.raises(TenantContextMissing):
        s.query(User).count()
    with pytest.raises(TenantContextMissing):
        s.execute(select(func.count()).select_from(User))
    s.close()
