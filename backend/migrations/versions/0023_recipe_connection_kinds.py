"""recipe connections: allowed paths, OAuth2 client credentials, Slack webhooks

Revision ID: 0023
Revises: 0022
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0023'
down_revision = '0022'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column('recipe_connections', 'kind', type_=sa.String(32), existing_type=sa.String(16), existing_nullable=False)
    op.add_column('recipe_connections', sa.Column('allowed_paths', postgresql.JSONB(), nullable=True))
    op.add_column('recipe_connections', sa.Column('client_id', sa.String(255), nullable=True))
    op.add_column('recipe_connections', sa.Column('token_url', sa.String(2000), nullable=True))
    op.add_column('recipe_connections', sa.Column('scope', sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column('recipe_connections', 'scope')
    op.drop_column('recipe_connections', 'token_url')
    op.drop_column('recipe_connections', 'client_id')
    op.drop_column('recipe_connections', 'allowed_paths')
    op.alter_column('recipe_connections', 'kind', type_=sa.String(16), existing_type=sa.String(32), existing_nullable=False)
