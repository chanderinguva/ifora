"""OIDC clients and client secrets

Revision ID: 0011
Revises: 0010
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'oidc_clients',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('client_id', sa.String(length=64), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('client_type', sa.String(length=16), nullable=False),
        sa.Column('token_endpoint_auth_method', sa.String(length=32), nullable=False),
        sa.Column('first_party', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('redirect_uris', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('post_logout_redirect_uris', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('allowed_scopes', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('grant_types', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'client_id', name='uq_oidc_clients_tenant_client_id'),
    )
    op.create_index(op.f('ix_oidc_clients_tenant_id'), 'oidc_clients', ['tenant_id'])
    op.create_index(op.f('ix_oidc_clients_client_id'), 'oidc_clients', ['client_id'])
    op.create_table(
        'oidc_client_secrets',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('client_pk', sa.Integer(), nullable=False),
        sa.Column('secret_hash', sa.String(length=255), nullable=False),
        sa.Column('hint', sa.String(length=8), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['client_pk'], ['oidc_clients.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_oidc_client_secrets_tenant_id'), 'oidc_client_secrets', ['tenant_id'])
    op.create_index(op.f('ix_oidc_client_secrets_client_pk'), 'oidc_client_secrets', ['client_pk'])


def downgrade() -> None:
    op.drop_table('oidc_client_secrets')
    op.drop_table('oidc_clients')
