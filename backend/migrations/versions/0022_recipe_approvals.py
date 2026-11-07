"""recipe jobs: approval state and paused time

Revision ID: 0022
Revises: 0021
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0022'
down_revision = '0021'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('recipe_jobs', sa.Column('approval', postgresql.JSONB(), nullable=True))
    op.add_column('recipe_jobs', sa.Column('paused_seconds', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('recipe_jobs', 'paused_seconds')
    op.drop_column('recipe_jobs', 'approval')
