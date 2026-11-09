"""application_self_service, access_requests

Revision ID: 0045
Revises: 0044
"""
from alembic import op
import sqlalchemy as sa

revision = '0045'
down_revision = '0044'
branch_labels = None
depends_on = None


def _tenant():
    return sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False, index=True)


def upgrade():
    op.create_table(
        'application_self_service', _tenant(),
        sa.Column('application_id', sa.Integer(), sa.ForeignKey('applications.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('reason_required', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        'access_requests', _tenant(),
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('application_id', sa.Integer(), sa.ForeignKey('applications.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('reason', sa.String(500)),
        sa.Column('status', sa.String(10), nullable=False, index=True),
        sa.Column('decided_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('decided_at', sa.DateTime(timezone=True)),
        sa.Column('decision_note', sa.String(500)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('uq_access_request_pending', 'access_requests', ['user_id', 'application_id'], unique=True, postgresql_where=sa.text("status = 'pending'"))


def downgrade():
    op.drop_table('access_requests')
    op.drop_table('application_self_service')
