"""provisioning apps: OAuth2 client-credentials settings

Revision ID: 0034
Revises: 0033
"""
from alembic import op
import sqlalchemy as sa

revision = '0034'
down_revision = '0033'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('provisioning_apps', sa.Column('token_url', sa.String(2000)))
    op.add_column('provisioning_apps', sa.Column('client_id', sa.String(255)))
    op.add_column('provisioning_apps', sa.Column('scope', sa.String(500)))


def downgrade() -> None:
    for c in ('scope', 'client_id', 'token_url'):
        op.drop_column('provisioning_apps', c)
