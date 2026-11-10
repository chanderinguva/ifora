"""callable recipes: child jobs (ADR 021 section 3)

Revision ID: 0049
Revises: 0048
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0049'
down_revision = '0048'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('recipe_jobs', sa.Column('parent_job_id', sa.Integer(), nullable=True))
    op.add_column('recipe_jobs', sa.Column('call_chain', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_index('ix_recipe_jobs_parent_job_id', 'recipe_jobs', ['parent_job_id'])


def downgrade() -> None:
    op.drop_index('ix_recipe_jobs_parent_job_id', table_name='recipe_jobs')
    op.drop_column('recipe_jobs', 'call_chain')
    op.drop_column('recipe_jobs', 'parent_job_id')
