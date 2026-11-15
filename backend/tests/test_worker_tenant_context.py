"""IFORA-19: background work always runs under an explicit tenant; one that lost its tenant fails closed."""

import pytest

from backend.app import tenancy
from backend.app.groups.model import Group
from backend.app.tenancy import TenantContextMissing, tenant_session
from tests.test_tenancy import b_session, tenant_b  # noqa: F401  (fixture)


def test_strict_session_refuses_a_missing_tenant_instead_of_using_the_default():
    with pytest.raises(TenantContextMissing):
        tenant_session(None, strict=True)
    s = tenant_session(None)  # interactive and test code keeps the single-tenant convenience
    assert s.info["tenant_id"] == tenancy.default_tenant_id()
    s.close()


def test_a_strict_session_is_scoped_to_the_tenant_it_was_given(db, tenant_b):  # noqa: F811
    g = Group(name="only-in-default")
    db.add(g)
    db.commit()
    s = tenant_session(tenant_b, strict=True)
    try:
        assert s.query(Group).filter(Group.name == "only-in-default").count() == 0
        s.add(Group(name="only-in-b"))
        s.commit()
    finally:
        s.close()
    assert db.query(Group).filter(Group.name == "only-in-b").count() == 0


def test_creating_tenant_owned_rows_without_any_tenant_context_is_refused():
    from backend.app.db import SessionLocal

    s = SessionLocal()  # no tenant bound at all
    try:
        s.add(Group(name="orphan"))
        with pytest.raises(TenantContextMissing):
            s.flush()
    finally:
        s.rollback()
        s.close()


def test_every_worker_loop_opens_tenant_sessions_strictly():
    """The two worker entry points name the tenant explicitly and use strict=True, so a lost id cannot fall back."""
    import inspect

    from backend.app.provisioning import worker as pw
    from backend.app.recipes import engine

    assert "tenant_session(tid, strict=True)" in inspect.getsource(pw.process_once)
    assert "tenant_session(tid, strict=True)" in inspect.getsource(engine.process_once)
    assert "strict=True" in inspect.getsource(engine._run_child_dry)
