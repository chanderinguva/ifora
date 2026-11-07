"""oidc clients: allowed_audiences for service (client_credentials) clients

Revision ID: 0019
Revises: 0018
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0019'
down_revision = '0018'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('oidc_clients', sa.Column('allowed_audiences', postgresql.JSONB(), nullable=False, server_default='[]'))


def downgrade() -> None:
    op.drop_column('oidc_clients', 'allowed_audiences')
