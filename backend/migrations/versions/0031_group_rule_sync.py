"""group rules: batched background activation state

Revision ID: 0031
Revises: 0030
"""
from alembic import op
import sqlalchemy as sa

revision = '0031'
down_revision = '0030'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('group_rules', sa.Column('sync_state', sa.String(8), nullable=False, server_default='idle'))
    op.add_column('group_rules', sa.Column('sync_cursor', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('group_rules', 'sync_cursor')
    op.drop_column('group_rules', 'sync_state')
