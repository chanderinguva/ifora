"""application icons (raster logos for My apps tiles)

Revision ID: 0036
Revises: 0035
"""
from alembic import op
import sqlalchemy as sa

revision = '0036'
down_revision = '0035'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'application_icons',
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False, index=True),
        sa.Column('application_id', sa.Integer(), sa.ForeignKey('applications.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('content_type', sa.String(20), nullable=False),
        sa.Column('data', sa.LargeBinary(), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table('application_icons')
