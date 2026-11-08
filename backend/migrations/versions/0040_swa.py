"""SWA: swa_configs, swa_credentials; applications.sign_on_mode gains 'swa'

Revision ID: 0040
Revises: 0039
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0040'
down_revision = '0039'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint('ck_applications_sign_on_mode', 'applications', type_='check')
    op.create_check_constraint('ck_applications_sign_on_mode', 'applications', "sign_on_mode IN ('none','bookmark','oidc','saml','swa')")
    op.create_table(
        'swa_configs',
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False, index=True),
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('application_id', sa.Integer(), sa.ForeignKey('applications.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('login_url', sa.String(2000), nullable=False),
        sa.Column('username_field', sa.String(64), nullable=False),
        sa.Column('password_field', sa.String(64), nullable=False),
        sa.Column('extra_fields', JSONB(), nullable=False),
        sa.Column('username_source', sa.String(10), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("username_source IN ('user','email','username')", name='ck_swa_username_source'),
    )
    op.create_table(
        'swa_credentials',
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False, index=True),
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('application_id', sa.Integer(), sa.ForeignKey('applications.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('username', sa.String(255)),
        sa.Column('secret', sa.LargeBinary(), nullable=False),
        sa.Column('key_id', sa.String(8), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('application_id', 'user_id', name='uq_swa_credentials_app_user'),
    )


def downgrade():
    op.drop_table('swa_credentials')
    op.drop_table('swa_configs')
    op.execute("DELETE FROM applications WHERE sign_on_mode = 'swa'")
    op.drop_constraint('ck_applications_sign_on_mode', 'applications', type_='check')
    op.create_check_constraint('ck_applications_sign_on_mode', 'applications', "sign_on_mode IN ('none','bookmark','oidc','saml')")
