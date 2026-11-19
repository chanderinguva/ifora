"""Access request lifecycle (IFORA-37): per-app approval policy with ordered stages, grant expiry, escalation and SoD rules.

Existing requests keep working: the new columns default to a single-stage, un-routed request that any administrator can decide,
exactly as before. Reversible; the downgrade drops only what this revision added.

Revision ID: 0064
Revises: 0063
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0064"
down_revision = "0063"
branch_labels = None
depends_on = None


def _tenant():
    return sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False, index=True)


def upgrade() -> None:
    op.create_table(
        "application_approval_policies",
        _tenant(),
        sa.Column("application_id", sa.Integer(), sa.ForeignKey("applications.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("timeout_hours", sa.Integer(), nullable=True),
        sa.Column("durations", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("timeout_hours IS NULL OR (timeout_hours BETWEEN 1 AND 8760)", name="ck_approval_policy_timeout"),
    )
    op.create_table(
        "application_approval_stages",
        _tenant(),
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("application_id", sa.Integer(), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("approver_kind", sa.String(10), nullable=False),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=True),
        sa.UniqueConstraint("application_id", "position", name="uq_approval_stage_position"),
        sa.CheckConstraint("position BETWEEN 1 AND 3", name="ck_approval_stage_position"),
        sa.CheckConstraint("approver_kind IN ('owner','manager','group')", name="ck_approval_stage_kind"),
        sa.CheckConstraint("(approver_kind = 'group') = (group_id IS NOT NULL)", name="ck_approval_stage_group"),
    )
    op.add_column("access_requests", sa.Column("routed", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("access_requests", sa.Column("stage", sa.SmallInteger(), nullable=False, server_default="1"))
    op.add_column("access_requests", sa.Column("stages_total", sa.SmallInteger(), nullable=False, server_default="1"))
    op.add_column("access_requests", sa.Column("duration_days", sa.Integer(), nullable=True))
    op.add_column("access_requests", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("access_requests", sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("access_requests", sa.Column("sod_conflict", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("access_requests", sa.Column("exception_reason", sa.String(500), nullable=True))
    op.create_index("ix_access_requests_expiry", "access_requests", ["expires_at"], postgresql_where=sa.text("status = 'approved' AND expires_at IS NOT NULL"))
    op.create_table(
        "access_request_decisions",
        _tenant(),
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.Integer(), sa.ForeignKey("access_requests.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("stage", sa.SmallInteger(), nullable=False),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decision", sa.String(10), nullable=False),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("request_id", "stage", name="uq_access_decision_stage"),
    )
    op.create_table(
        "sod_rules",
        _tenant(),
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("app_a_id", sa.Integer(), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("app_b_id", sa.Integer(), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("note", sa.String(200), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("app_a_id", "app_b_id", name="uq_sod_rule_pair"),
        sa.CheckConstraint("app_a_id < app_b_id", name="ck_sod_rule_order"),
    )


def downgrade() -> None:
    op.drop_table("sod_rules")
    op.drop_table("access_request_decisions")
    op.drop_index("ix_access_requests_expiry", table_name="access_requests")
    for c in ("exception_reason", "sod_conflict", "escalated_at", "expires_at", "duration_days", "stages_total", "stage", "routed"):
        op.drop_column("access_requests", c)
    op.drop_table("application_approval_stages")
    op.drop_table("application_approval_policies")
