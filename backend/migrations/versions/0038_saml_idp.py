"""SAML 2.0 IdP: providers, signing keys, pending requests; applications.sign_on_mode gains 'saml'

Revision ID: 0038
Revises: 0037
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0038'
down_revision = '0037'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint('ck_applications_sign_on_mode', 'applications', type_='check')
    op.create_check_constraint('ck_applications_sign_on_mode', 'applications', "sign_on_mode IN ('none','bookmark','oidc','saml')")
    op.create_table(
        'saml_providers',
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False, index=True),
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('application_id', sa.Integer(), sa.ForeignKey('applications.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('sp_entity_id', sa.String(500), nullable=False),
        sa.Column('acs_url', sa.String(2000), nullable=False),
        sa.Column('audience', sa.String(500)),
        sa.Column('name_id_format', sa.String(12), nullable=False),
        sa.Column('signing', sa.String(10), nullable=False),
        sa.Column('attribute_mappings', JSONB(), nullable=False),
        sa.Column('sp_cert', sa.Text()),
        sa.Column('require_signed_requests', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('default_relay_state', sa.String(512)),
        sa.Column('validity_seconds', sa.Integer(), nullable=False, server_default='300'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('tenant_id', 'sp_entity_id', name='uq_saml_providers_tenant_entity'),
        sa.CheckConstraint("name_id_format IN ('email','persistent')", name='ck_saml_name_id_format'),
        sa.CheckConstraint("signing IN ('assertion','response','both')", name='ck_saml_signing'),
        sa.CheckConstraint('validity_seconds BETWEEN 60 AND 3600', name='ck_saml_validity'),
    )
    op.create_table(
        'saml_signing_keys',
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False, index=True),
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('private_key_enc', sa.Text(), nullable=False),
        sa.Column('cert_pem', sa.Text(), nullable=False),
        sa.Column('not_after', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(8), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('active','retired')", name='ck_saml_key_status'),
    )
    op.create_table(
        'saml_pending_requests',
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False, index=True),
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('request_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('provider_id', sa.Integer(), sa.ForeignKey('saml_providers.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('in_response_to', sa.String(256), nullable=False),
        sa.Column('relay_state', sa.String(512)),
        sa.Column('auth_after', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('decided_at', sa.DateTime(timezone=True)),
    )


def downgrade():
    op.drop_table('saml_pending_requests')
    op.drop_table('saml_signing_keys')
    op.drop_table('saml_providers')
    op.execute("UPDATE applications SET sign_on_mode = 'none', launch_url = NULL WHERE sign_on_mode = 'saml'")
    op.drop_constraint('ck_applications_sign_on_mode', 'applications', type_='check')
    op.create_check_constraint('ck_applications_sign_on_mode', 'applications', "sign_on_mode IN ('none','bookmark','oidc')")
