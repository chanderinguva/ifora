"""Test-created tenants must not survive the per-test database reset."""

from backend.app.db import engine
from backend.app.tenancy import default_tenant_id
from tests.conftest import reset_test_rows


def test_reset_removes_temporary_tenants_and_preserves_default():
    seeded_id = default_tenant_id()
    # Reproduce the SCIM -> recipes collision in one worker, independent of order.
    for _ in range(2):
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "INSERT INTO tenants (slug, name, created_at) VALUES (%s, %s, now())",
                ("other", "Other"),
            )
        reset_test_rows()
        with engine.connect() as conn:
            assert conn.exec_driver_sql("SELECT id, slug FROM tenants").all() == [(seeded_id, "default")]
        assert default_tenant_id() == seeded_id
