"""Durable Slack message shortcut capture queue.

Revision ID: 0057
Revises: 0056
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "slack_idea_captures",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("dedupe_key", sa.String(length=300), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "dedupe_key", name="uq_slack_idea_capture_event"),
    )
    op.create_index("ix_slack_idea_captures_tenant_id", "slack_idea_captures", ["tenant_id"])
    op.create_index("ix_slack_idea_captures_status", "slack_idea_captures", ["status"])
    op.create_index("ix_slack_idea_captures_next_attempt_at", "slack_idea_captures", ["next_attempt_at"])
    op.create_index("ix_slack_idea_captures_locked_until", "slack_idea_captures", ["locked_until"])


def downgrade():
    op.drop_table("slack_idea_captures")

