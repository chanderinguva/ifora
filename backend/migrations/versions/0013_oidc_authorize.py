"""oidc pending authorization requests, consents, authorization codes

Revision ID: 0013
Revises: 0012
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def _common():
    return [
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        'oidc_pending_requests', *_common(),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('client_pk', sa.Integer(), nullable=False),
        sa.Column('redirect_uri', sa.String(2000), nullable=False),
        sa.Column('scopes', JSONB, nullable=False),
        sa.Column('state', sa.String(512), nullable=True),
        sa.Column('nonce', sa.String(512), nullable=True),
        sa.Column('code_challenge', sa.String(128), nullable=False),
        sa.Column('prompt', sa.String(32), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['client_pk'], ['oidc_clients.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('request_hash'),
    )
    op.create_index(op.f('ix_oidc_pending_requests_tenant_id'), 'oidc_pending_requests', ['tenant_id'])
    op.create_index(op.f('ix_oidc_pending_requests_client_pk'), 'oidc_pending_requests', ['client_pk'])

    op.create_table(
        'oidc_consents', *_common(),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('client_pk', sa.Integer(), nullable=False),
        sa.Column('scopes', JSONB, nullable=False),
        sa.Column('granted_via', sa.String(16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['client_pk'], ['oidc_clients.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'client_pk', name='uq_oidc_consents_user_client'),
    )
    op.create_index(op.f('ix_oidc_consents_tenant_id'), 'oidc_consents', ['tenant_id'])
    op.create_index(op.f('ix_oidc_consents_user_id'), 'oidc_consents', ['user_id'])
    op.create_index(op.f('ix_oidc_consents_client_pk'), 'oidc_consents', ['client_pk'])

    op.create_table(
        'oidc_codes', *_common(),
        sa.Column('code_hash', sa.String(64), nullable=False),
        sa.Column('client_pk', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('redirect_uri', sa.String(2000), nullable=False),
        sa.Column('scopes', JSONB, nullable=False),
        sa.Column('nonce', sa.String(512), nullable=True),
        sa.Column('code_challenge', sa.String(128), nullable=False),
        sa.Column('auth_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('amr', JSONB, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['client_pk'], ['oidc_clients.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code_hash'),
    )
    op.create_index(op.f('ix_oidc_codes_tenant_id'), 'oidc_codes', ['tenant_id'])
    op.create_index(op.f('ix_oidc_codes_client_pk'), 'oidc_codes', ['client_pk'])
    op.create_index(op.f('ix_oidc_codes_user_id'), 'oidc_codes', ['user_id'])


def downgrade() -> None:
    op.drop_table('oidc_codes')
    op.drop_table('oidc_consents')
    op.drop_table('oidc_pending_requests')
