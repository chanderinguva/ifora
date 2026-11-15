"""Admin step-up: when and how a session last proved a second factor (IFORA-33).

Two nullable columns on `sessions`; no data is rewritten. Reversible.

Revision ID: 0062
Revises: 0061
"""

import sqlalchemy as sa
from alembic import op

revision = "0062"
down_revision = "0061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("stepup_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sessions", sa.Column("stepup_method", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "stepup_method")
    op.drop_column("sessions", "stepup_at")
