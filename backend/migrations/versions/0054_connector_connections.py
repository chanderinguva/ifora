"""pre-built connectors: connection columns

Revision ID: 0054
Revises: 0053
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0054'
down_revision = '0053'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('recipe_connections', sa.Column('connector_id', sa.String(32), nullable=True))
    op.add_column('recipe_connections', sa.Column('connector_version', sa.Integer(), nullable=True))
    op.add_column('recipe_connections', sa.Column('config', JSONB(), nullable=True))


def downgrade():
    op.drop_column('recipe_connections', 'config')
    op.drop_column('recipe_connections', 'connector_version')
    op.drop_column('recipe_connections', 'connector_id')
