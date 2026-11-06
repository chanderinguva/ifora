"""oidc pending requests: auth_after for forced re-authentication

Revision ID: 0018
Revises: 0017
"""
from alembic import op
import sqlalchemy as sa

revision = '0018'
down_revision = '0017'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('oidc_pending_requests', sa.Column('auth_after', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('oidc_pending_requests', 'auth_after')
