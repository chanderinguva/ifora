"""network_zones, app_auth_policies

Revision ID: 0041
Revises: 0040
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0041'
down_revision = '0040'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'network_zones',
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False, index=True),
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(80), nullable=False),
        sa.Column('cidrs', JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('tenant_id', 'name', name='uq_network_zones_tenant_name'),
    )
    op.create_table(
        'app_auth_policies',
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False, index=True),
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('application_id', sa.Integer(), sa.ForeignKey('applications.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('require_mfa', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('reauth_minutes', sa.Integer()),
        sa.Column('allowed_zone_ids', JSONB(), nullable=False),
        sa.Column('blocked_zone_ids', JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('reauth_minutes IS NULL OR reauth_minutes BETWEEN 5 AND 1440', name='ck_app_policy_reauth'),
    )


def downgrade():
    op.drop_table('app_auth_policies')
    op.drop_table('network_zones')
