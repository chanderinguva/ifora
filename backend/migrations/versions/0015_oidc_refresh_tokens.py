"""oidc refresh tokens

Revision ID: 0015
Revises: 0014
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'oidc_refresh_tokens',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('token_hash', sa.String(64), nullable=False),
        sa.Column('family_id', sa.String(36), nullable=False),
        sa.Column('parent_id', sa.Integer(), nullable=True),
        sa.Column('code_id', sa.Integer(), nullable=True),
        sa.Column('client_pk', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('scopes', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('auth_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('amr', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('absolute_expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['code_id'], ['oidc_codes.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['client_pk'], ['oidc_clients.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash'),
    )
    for col in ('tenant_id', 'family_id', 'code_id', 'client_pk', 'user_id'):
        op.create_index(op.f(f'ix_oidc_refresh_tokens_{col}'), 'oidc_refresh_tokens', [col])


def downgrade() -> None:
    op.drop_table('oidc_refresh_tokens')
