"""group admin roles, group metadata and types

Revision ID: 0047
Revises: 0046
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0047'
down_revision = '0046'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'group_admin_roles',
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False, index=True),
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('group_id', sa.Integer(), sa.ForeignKey('groups.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('role', sa.String(32), nullable=False),
        sa.Column('granted_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('group_id', 'role', name='uq_group_admin_role'),
    )
    op.add_column('groups', sa.Column('owner_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True))
    op.create_index('ix_groups_owner_user_id', 'groups', ['owner_user_id'])
    op.add_column('groups', sa.Column('sensitivity', sa.String(8), nullable=True))
    op.add_column('groups', sa.Column('review_by', sa.Date(), nullable=True))
    op.add_column('groups', sa.Column('tags', JSONB(), nullable=False, server_default='[]'))
    op.execute("UPDATE groups SET type = 'other' WHERE type = 'standard'")
    op.alter_column('groups', 'type', server_default='other')
    # "no role = full organization administrator" is gone (a user who leaves a role group must not fall back to full
    # access), so make today's implicit organization administrators explicit.
    op.execute("""
        INSERT INTO admin_role_assignments (tenant_id, user_id, role, granted_by, created_at)
        SELECT u.tenant_id, u.id, 'org_admin', NULL, now()
        FROM users u
        WHERE u.is_admin AND NOT u.is_super_admin
          AND NOT EXISTS (SELECT 1 FROM admin_role_assignments a WHERE a.user_id = u.id)
    """)


def downgrade():
    op.drop_table('group_admin_roles')
    op.drop_column('groups', 'tags')
    op.drop_column('groups', 'review_by')
    op.drop_column('groups', 'sensitivity')
    op.drop_index('ix_groups_owner_user_id', table_name='groups')
    op.drop_column('groups', 'owner_user_id')
    op.alter_column('groups', 'type', server_default=None)
