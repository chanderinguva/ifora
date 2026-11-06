"""scim tokens and links

Revision ID: 0016
Revises: 0015
"""
from alembic import op
import sqlalchemy as sa

revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'scim_tokens',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('token_hash', sa.String(64), nullable=False),
        sa.Column('token_prefix', sa.String(16), nullable=False),
        sa.Column('created_by_user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash'),
    )
    op.create_index(op.f('ix_scim_tokens_tenant_id'), 'scim_tokens', ['tenant_id'])
    op.create_table(
        'scim_links',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('group_id', sa.Integer(), nullable=True),
        sa.Column('external_id', sa.String(255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['group_id'], ['groups.id'], ondelete='CASCADE'),
        sa.CheckConstraint('(user_id IS NOT NULL) <> (group_id IS NOT NULL)', name='ck_scim_links_one_target'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'user_id', name='uq_scim_links_tenant_user'),
        sa.UniqueConstraint('tenant_id', 'group_id', name='uq_scim_links_tenant_group'),
    )
    op.create_index(op.f('ix_scim_links_tenant_id'), 'scim_links', ['tenant_id'])
    op.create_index('uq_scim_links_user_external', 'scim_links', ['tenant_id', 'external_id'], unique=True,
                    postgresql_where=sa.text('user_id IS NOT NULL'))
    op.create_index('uq_scim_links_group_external', 'scim_links', ['tenant_id', 'external_id'], unique=True,
                    postgresql_where=sa.text('group_id IS NOT NULL'))


def downgrade() -> None:
    op.drop_table('scim_links')
    op.drop_table('scim_tokens')
