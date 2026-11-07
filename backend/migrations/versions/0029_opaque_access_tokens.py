"""OIDC: opaque access tokens (per-client format) and their table

Revision ID: 0029
Revises: 0028
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0029'
down_revision = '0028'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('oidc_clients', sa.Column('access_token_format', sa.String(8), nullable=False, server_default='jwt'))
    op.create_table(
        'oidc_access_tokens',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False, index=True),
        sa.Column('token_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('client_pk', sa.Integer(), sa.ForeignKey('oidc_clients.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('sub', sa.String(64), nullable=False),
        sa.Column('audience', sa.String(255), nullable=False),
        sa.Column('scopes', postgresql.JSONB(), nullable=False),
        sa.Column('auth_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('oidc_access_tokens')
    op.drop_column('oidc_clients', 'access_token_format')
