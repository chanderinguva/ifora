"""admin API tokens

Revision ID: 0053
Revises: 0052
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0053'
down_revision = '0052'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'api_tokens',
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False, index=True),
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('token_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('token_prefix', sa.String(16), nullable=False),
        sa.Column('read_only', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('allowed_cidrs', JSONB(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_used_ip', sa.String(45), nullable=True),
    )
    op.create_index('uq_api_tokens_user_name_live', 'api_tokens', ['user_id', 'name'], unique=True, postgresql_where=sa.text('revoked_at IS NULL'))


def downgrade():
    op.drop_index('uq_api_tokens_user_name_live', 'api_tokens')
    op.drop_table('api_tokens')
