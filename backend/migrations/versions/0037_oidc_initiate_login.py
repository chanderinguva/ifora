"""oidc clients: initiate_login_uri (OIDC third-party initiated login, used by IdP-initiated launch)

Revision ID: 0037
Revises: 0036
"""
from alembic import op
import sqlalchemy as sa

revision = '0037'
down_revision = '0036'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('oidc_clients', sa.Column('initiate_login_uri', sa.String(2000), nullable=True))


def downgrade():
    op.drop_column('oidc_clients', 'initiate_login_uri')
