"""org_security_policy, password_history, users.password_changed_at

Revision ID: 0046
Revises: 0045
"""
from alembic import op
import sqlalchemy as sa

revision = '0046'
down_revision = '0045'
branch_labels = None
depends_on = None


def _tenant():
    return sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False, index=True)


def upgrade():
    op.add_column('users', sa.Column('password_changed_at', sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        'org_security_policy', _tenant(),
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('min_length', sa.Integer(), nullable=False), sa.Column('require_mixed_case', sa.Boolean(), nullable=False),
        sa.Column('require_digit', sa.Boolean(), nullable=False), sa.Column('require_symbol', sa.Boolean(), nullable=False),
        sa.Column('no_user_info', sa.Boolean(), nullable=False), sa.Column('history_count', sa.Integer(), nullable=False),
        sa.Column('max_age_days', sa.Integer(), nullable=False), sa.Column('max_failed_attempts', sa.Integer(), nullable=False),
        sa.Column('lockout_minutes', sa.Integer(), nullable=False), sa.Column('session_lifetime_hours', sa.Integer(), nullable=False),
        sa.Column('idle_timeout_minutes', sa.Integer(), nullable=False),
        sa.Column('updated_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('tenant_id', name='uq_org_security_policy_tenant'),
    )
    op.create_table(
        'password_history', _tenant(),
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table('password_history')
    op.drop_table('org_security_policy')
    op.drop_column('users', 'password_changed_at')
