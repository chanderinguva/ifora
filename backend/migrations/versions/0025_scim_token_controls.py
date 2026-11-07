"""scim: token scopes, IP allow-list, rotation link, hard-delete policy, public group ids

Revision ID: 0025
Revises: 0024
"""
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0025'
down_revision = '0024'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('scim_tokens', sa.Column('read_only', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('scim_tokens', sa.Column('users_only', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('scim_tokens', sa.Column('allowed_cidrs', postgresql.JSONB(), nullable=True))
    op.add_column('scim_tokens', sa.Column('replaced_by_id', sa.Integer(), nullable=True))
    op.add_column('scim_tokens', sa.Column('hard_delete_after_days', sa.Integer(), nullable=True))
    op.create_table(
        'scim_deprovisioned',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False, index=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('token_id', sa.Integer(), sa.ForeignKey('scim_tokens.id', ondelete='CASCADE'), nullable=False),
        sa.Column('deactivated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('tenant_id', 'user_id', name='uq_scim_deprovisioned_tenant_user'),
    )
    # S8: opaque, unguessable group ids for SCIM (integer ids stay valid on lookup for IdPs that already stored them)
    op.add_column('groups', sa.Column('public_id', sa.String(36), nullable=True))
    conn = op.get_bind()
    for (gid,) in conn.execute(sa.text("SELECT id FROM groups")).fetchall():
        conn.execute(sa.text("UPDATE groups SET public_id = :p WHERE id = :i"), {"p": str(uuid.uuid4()), "i": gid})
    op.alter_column('groups', 'public_id', nullable=False)
    op.create_unique_constraint('uq_groups_public_id', 'groups', ['public_id'])


def downgrade() -> None:
    op.drop_constraint('uq_groups_public_id', 'groups', type_='unique')
    op.drop_column('groups', 'public_id')
    op.drop_table('scim_deprovisioned')
    for c in ('hard_delete_after_days', 'replaced_by_id', 'allowed_cidrs', 'users_only', 'read_only'):
        op.drop_column('scim_tokens', c)
