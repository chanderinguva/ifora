"""OIDC signing keys

Revision ID: 0009
Revises: 0008
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'oidc_signing_keys',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('kid', sa.String(length=64), nullable=False),
        sa.Column('alg', sa.String(length=16), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('private_pem_encrypted', sa.Text(), nullable=True),
        sa.Column('public_jwk', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('activate_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('retire_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'kid', name='uq_oidc_signing_keys_tenant_kid'),
    )
    op.create_index(op.f('ix_oidc_signing_keys_tenant_id'), 'oidc_signing_keys', ['tenant_id'])
    op.create_index(op.f('ix_oidc_signing_keys_status'), 'oidc_signing_keys', ['status'])
    op.create_index(
        'uq_oidc_signing_keys_one_active', 'oidc_signing_keys', ['tenant_id'],
        unique=True, postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index('uq_oidc_signing_keys_one_active', table_name='oidc_signing_keys', postgresql_where=sa.text("status = 'active'"))
    op.drop_index(op.f('ix_oidc_signing_keys_status'), table_name='oidc_signing_keys')
    op.drop_index(op.f('ix_oidc_signing_keys_tenant_id'), table_name='oidc_signing_keys')
    op.drop_table('oidc_signing_keys')
