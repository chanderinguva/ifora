"""sessions record when and how the user authenticated (auth_time, amr) for OIDC claims

Revision ID: 0008
Revises: 0007
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('sessions', sa.Column('auth_time', sa.DateTime(timezone=True), nullable=True))
    op.add_column('sessions', sa.Column('amr', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    # Sessions that pre-date tracking: auth time = creation time; method unknown, so claim only a password
    # (never over-claim MFA).
    op.execute("UPDATE sessions SET auth_time = created_at, amr = '[\"pwd\"]'::jsonb")
    op.alter_column('sessions', 'auth_time', nullable=False)
    op.alter_column('sessions', 'amr', nullable=False)


def downgrade() -> None:
    op.drop_column('sessions', 'amr')
    op.drop_column('sessions', 'auth_time')
