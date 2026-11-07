"""oidc clients: jwks for private_key_jwt authentication

Revision ID: 0020
Revises: 0019
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0020'
down_revision = '0019'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('oidc_clients', sa.Column('jwks', postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column('oidc_clients', 'jwks')
