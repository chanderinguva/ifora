"""IFORA-18 RLS spike: the flag-gated policy isolates tenants for a non-owner role and fails closed without a tenant."""

import importlib.util
from pathlib import Path

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import text

from backend.app.db import engine
from backend.app.groups.model import Group
from backend.app.tenancy import Tenant, tenant_session, unscoped
from tests.conftest import make_user

PATH = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "0058_rls_spike.py"
ROLE = "ifora_rls_probe"


def _migration():
    spec = importlib.util.spec_from_file_location("rls_spike", PATH)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _run(fn_name, monkeypatch=None):
    m = _migration()
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            getattr(m, fn_name)()


@pytest.fixture
def rls(monkeypatch):
    monkeypatch.setenv("IFORA_RLS_SPIKE", "1")
    with engine.begin() as conn:
        conn.exec_driver_sql(f"DROP ROLE IF EXISTS {ROLE}")
        conn.exec_driver_sql(f"CREATE ROLE {ROLE} NOLOGIN")
        conn.exec_driver_sql(f"GRANT USAGE ON SCHEMA public TO {ROLE}")
        conn.exec_driver_sql(f"GRANT SELECT, INSERT ON user_group_membership TO {ROLE}")
    _run("upgrade")
    yield
    _run("downgrade")
    with engine.begin() as conn:
        conn.exec_driver_sql(f"REVOKE ALL ON user_group_membership FROM {ROLE}")
        conn.exec_driver_sql(f"REVOKE ALL ON SCHEMA public FROM {ROLE}")
        conn.exec_driver_sql(f"DROP ROLE {ROLE}")


def test_flag_off_changes_nothing(monkeypatch):
    monkeypatch.delenv("IFORA_RLS_SPIKE", raising=False)
    _run("upgrade")
    with engine.connect() as conn:
        assert conn.execute(text("select relrowsecurity from pg_class where relname='user_group_membership'")).scalar() is False


def test_policy_shows_each_tenant_only_its_rows_and_none_without_one(db, rls):
    from sqlalchemy import insert

    from backend.app.groups.model import user_group_association as m

    with unscoped(db):
        t2 = Tenant(slug="rls-b", name="B")
        db.add(t2)
        db.commit()
        tid2 = t2.id
    a = make_user(db, "rls-a@example.com")
    ga = Group(name="rls-ga")
    db.add(ga)
    db.commit()
    db.execute(insert(m).values(user_id=a.id, group_id=ga.id))
    db.commit()
    sb = tenant_session(tid2)
    b = make_user(sb, "rls-b@example.com")
    gb = Group(name="rls-gb")
    sb.add(gb)
    sb.commit()
    sb.execute(insert(m).values(user_id=b.id, group_id=gb.id))
    sb.commit()
    b_id = b.id
    sb.close()
    a_id, a_tenant = a.id, a.tenant_id
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(f"SET LOCAL ROLE {ROLE}")
            assert conn.exec_driver_sql("select count(*) from user_group_membership").scalar() == 0  # no tenant: nothing
            conn.exec_driver_sql(f"SET LOCAL app.tenant_id = '{a_tenant}'")
            assert conn.exec_driver_sql("select user_id from user_group_membership").scalars().all() == [a_id]
            conn.exec_driver_sql(f"SET LOCAL app.tenant_id = '{tid2}'")
            assert conn.exec_driver_sql("select user_id from user_group_membership").scalars().all() == [b_id]
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql("DELETE FROM user_group_membership WHERE tenant_id = %s", (tid2,))
            for t in ("users", "groups"):
                conn.exec_driver_sql(f"DELETE FROM {t} WHERE tenant_id = %s", (tid2,))
            conn.exec_driver_sql("DELETE FROM tenants WHERE id = %s", (tid2,))
