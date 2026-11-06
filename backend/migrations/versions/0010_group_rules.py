"""group rules: attribute-based automatic membership

Revision ID: 0010
Revises: 0009
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'group_rules',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('match', sa.String(length=3), nullable=False),
        sa.Column('conditions', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'name', name='uq_group_rules_tenant_name'),
    )
    op.create_index(op.f('ix_group_rules_tenant_id'), 'group_rules', ['tenant_id'])
    op.create_table(
        'group_rule_targets',
        sa.Column('rule_id', sa.Integer(), nullable=False),
        sa.Column('group_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['rule_id'], ['group_rules.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['group_id'], ['groups.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('rule_id', 'group_id'),
    )
    op.add_column('user_group_membership', sa.Column('rule_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_membership_rule_id', 'user_group_membership', 'group_rules', ['rule_id'], ['id'], ondelete='CASCADE')
    op.create_index(op.f('ix_user_group_membership_rule_id'), 'user_group_membership', ['rule_id'])


def downgrade() -> None:
    op.drop_index(op.f('ix_user_group_membership_rule_id'), table_name='user_group_membership')
    op.drop_constraint('fk_membership_rule_id', 'user_group_membership', type_='foreignkey')
    op.drop_column('user_group_membership', 'rule_id')
    op.drop_table('group_rule_targets')
    op.drop_index(op.f('ix_group_rules_tenant_id'), table_name='group_rules')
    op.drop_table('group_rules')
