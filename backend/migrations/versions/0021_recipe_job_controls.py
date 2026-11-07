"""recipe jobs: error-handler state, cancel request, rerun link

Revision ID: 0021
Revises: 0020
"""
from alembic import op
import sqlalchemy as sa

revision = '0021'
down_revision = '0020'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('recipe_jobs', sa.Column('in_handler', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('recipe_jobs', sa.Column('cancel_requested', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('recipe_jobs', sa.Column('rerun_of', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('recipe_jobs', 'rerun_of')
    op.drop_column('recipe_jobs', 'cancel_requested')
    op.drop_column('recipe_jobs', 'in_handler')
