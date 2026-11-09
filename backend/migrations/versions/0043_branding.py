"""org_branding, org_logos, email_templates

Revision ID: 0043
Revises: 0042
"""
from alembic import op
import sqlalchemy as sa

revision = '0043'
down_revision = '0042'
branch_labels = None
depends_on = None


def _tenant():
    return sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False, index=True)


def upgrade():
    op.create_table(
        'org_branding', _tenant(),
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('display_name', sa.String(60)), sa.Column('primary_color', sa.String(7)), sa.Column('tagline', sa.String(160)),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('tenant_id', name='uq_org_branding_tenant'),
    )
    op.create_table(
        'org_logos', _tenant(),
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('content_type', sa.String(20), nullable=False), sa.Column('data', sa.LargeBinary(), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False), sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('tenant_id', name='uq_org_logos_tenant'),
    )
    op.create_table(
        'email_templates', _tenant(),
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('key', sa.String(20), nullable=False), sa.Column('subject', sa.String(200), nullable=False),
        sa.Column('body', sa.Text(), nullable=False), sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('tenant_id', 'key', name='uq_email_templates_tenant_key'),
    )


def downgrade():
    op.drop_table('email_templates')
    op.drop_table('org_logos')
    op.drop_table('org_branding')
