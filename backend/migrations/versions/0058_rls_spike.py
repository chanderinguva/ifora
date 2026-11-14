"""IFORA-18: row-level security spike on user_group_membership (flag-gated, off by default).

The decision (not a rollout) is in scope: see docs/architecture/027-tenant-rls-decision.md (kept locally). With
IFORA_RLS_SPIKE unset or 0 this migration does nothing, so no environment changes. With IFORA_RLS_SPIKE=1 it turns
row-level security on for one table and adds a policy that only admits rows whose tenant_id equals the transaction's
`app.tenant_id`. The table owner (the application's role today) bypasses RLS unless FORCE is used, so enabling the
flag alone changes nothing for the application; it exists to prove the policy against a non-owner role.

Revision ID: 0058
Revises: 0057
"""

import os

from alembic import op

revision = "0058"
down_revision = "0057"
branch_labels = None
depends_on = None

TABLE = "user_group_membership"
POLICY = "tenant_isolation"


def _enabled() -> bool:
    return os.environ.get("IFORA_RLS_SPIKE", "0") == "1"


def upgrade() -> None:
    if not _enabled():
        return
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    # current_setting(..., true) is NULL when unset, so an unset tenant matches no rows (fails closed).
    op.execute(
        f"""CREATE POLICY {POLICY} ON {TABLE}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::integer)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::integer)"""
    )


def downgrade() -> None:
    # Always safe to run, whatever the flag was when upgrading.
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {TABLE}")
    op.execute(f"ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY")
