"""user_app_sections, user_app_prefs

Revision ID: 0044
Revises: 0043
"""
from alembic import op
import sqlalchemy as sa

revision = '0044'
down_revision = '0043'
branch_labels = None
depends_on = None


def _tenant():
    return sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False, index=True)


def upgrade():
    op.create_table(
        'user_app_sections', _tenant(),
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('name', sa.String(40), nullable=False), sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.UniqueConstraint('user_id', 'name', name='uq_user_app_sections_name'),
    )
    op.create_table(
        'user_app_prefs', _tenant(),
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('application_id', sa.Integer(), sa.ForeignKey('applications.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('favorite', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('section_id', sa.Integer(), sa.ForeignKey('user_app_sections.id', ondelete='SET NULL'), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_launched_at', sa.DateTime(timezone=True)),
        sa.Column('launch_count', sa.Integer(), nullable=False, server_default='0'),
        sa.UniqueConstraint('user_id', 'application_id', name='uq_user_app_prefs_app'),
    )


def downgrade():
    op.drop_table('user_app_prefs')
    op.drop_table('user_app_sections')
