"""Migrations are the source of truth for the schema."""

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from backend.app.db import Base, engine
from tests.conftest import alembic_config


def test_models_and_migrations_have_not_drifted():
    """If this fails, a model changed without a new migration (run `alembic revision --autogenerate`)."""
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
    assert diff == []


def test_downgrade_and_upgrade_roundtrip():
    cfg = alembic_config()
    command.downgrade(cfg, "base")
    with engine.connect() as conn:
        tables = set(__import__("sqlalchemy").inspect(conn).get_table_names())
    assert tables <= {"alembic_version"}
    command.upgrade(cfg, "head")
    from backend.app.tenancy import reset_tenant_cache

    reset_tenant_cache()
    with engine.connect() as conn:
        tables = set(__import__("sqlalchemy").inspect(conn).get_table_names())
    assert {"users", "groups", "sessions", "audit_events", "user_group_membership"} <= tables
