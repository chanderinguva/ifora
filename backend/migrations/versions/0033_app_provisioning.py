"""outbound provisioning: apps, assignments, links, tasks

Revision ID: 0033
Revises: 0032
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0033'
down_revision = '0032'
branch_labels = None
depends_on = None

TENANT = lambda: sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False, index=True)  # noqa: E731


def upgrade() -> None:
    op.create_table(
        'provisioning_apps',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        TENANT(),
        sa.Column('public_id', sa.String(36), nullable=False, unique=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.String(500)),
        sa.Column('kind', sa.String(8), nullable=False),
        sa.Column('base_url', sa.String(2000), nullable=False),
        sa.Column('auth_type', sa.String(16), nullable=False),
        sa.Column('header_name', sa.String(100)),
        sa.Column('secret_enc', sa.Text(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('options', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('mapping', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('rest_config', postgresql.JSONB()),
        sa.Column('last_test_at', sa.DateTime(timezone=True)),
        sa.Column('last_test_ok', sa.Boolean()),
        sa.Column('last_test_message', sa.String(300)),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('tenant_id', 'name', name='uq_provisioning_apps_tenant_name'),
    )
    op.create_table(
        'provisioning_assignments',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        TENANT(),
        sa.Column('app_id', sa.Integer(), sa.ForeignKey('provisioning_apps.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), index=True),
        sa.Column('group_id', sa.Integer(), sa.ForeignKey('groups.id', ondelete='CASCADE'), index=True),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('(user_id IS NULL) <> (group_id IS NULL)', name='ck_prov_assignment_one_subject'),
    )
    op.create_index('uq_prov_assign_user', 'provisioning_assignments', ['app_id', 'user_id'], unique=True, postgresql_where=sa.text('user_id IS NOT NULL'))
    op.create_index('uq_prov_assign_group', 'provisioning_assignments', ['app_id', 'group_id'], unique=True, postgresql_where=sa.text('group_id IS NOT NULL'))
    op.create_table(
        'provisioning_links',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        TENANT(),
        sa.Column('app_id', sa.Integer(), sa.ForeignKey('provisioning_apps.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('resource_type', sa.String(8), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('group_id', sa.Integer(), sa.ForeignKey('groups.id', ondelete='SET NULL')),
        sa.Column('label', sa.String(255), nullable=False, server_default=''),
        sa.Column('remote_id', sa.String(255), nullable=False),
        sa.Column('state', sa.String(16), nullable=False, server_default='synced'),
        sa.Column('payload_hash', sa.String(64)),
        sa.Column('last_synced_at', sa.DateTime(timezone=True)),
        sa.Column('last_error', sa.String(500)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("resource_type IN ('user','group')", name='ck_prov_link_type'),
    )
    op.create_index('uq_prov_link_user', 'provisioning_links', ['app_id', 'user_id'], unique=True, postgresql_where=sa.text('user_id IS NOT NULL'))
    op.create_index('uq_prov_link_group', 'provisioning_links', ['app_id', 'group_id'], unique=True, postgresql_where=sa.text('group_id IS NOT NULL'))
    op.create_table(
        'provisioning_tasks',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        TENANT(),
        sa.Column('app_id', sa.Integer(), sa.ForeignKey('provisioning_apps.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('resource_type', sa.String(8), nullable=False),
        sa.Column('user_id', sa.Integer()),
        sa.Column('group_id', sa.Integer()),
        sa.Column('link_id', sa.Integer()),
        sa.Column('op', sa.String(16), nullable=False, server_default='sync'),
        sa.Column('status', sa.String(10), nullable=False, server_default='queued'),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('locked_until', sa.DateTime(timezone=True)),
        sa.Column('last_error', sa.String(500)),
        sa.Column('result', sa.String(40)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True)),
    )
    op.create_index('ix_prov_tasks_due', 'provisioning_tasks', ['status', 'next_run_at'])


def downgrade() -> None:
    for t in ('provisioning_tasks', 'provisioning_links', 'provisioning_assignments', 'provisioning_apps'):
        op.drop_table(t)
