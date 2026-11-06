"""tenant-aware data model: tenants table, tenant_id on tenant-owned tables, per-tenant uniqueness

Revision ID: 0007
Revises: 0006
"""
from alembic import op
import sqlalchemy as sa


revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None

# table -> parent table/column used to inherit the tenant when backfilling (None = default tenant)
OWNED = ['users', 'groups', 'sessions', 'audit_events', 'user_mfa', 'mfa_recovery_codes',
         'mfa_challenges', 'passkeys', 'webauthn_challenges']


def upgrade() -> None:
    op.create_table(
        'tenants',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('slug', sa.String(length=63), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=20), server_default='active', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug'),
    )
    op.execute("INSERT INTO tenants (slug, name, status, created_at) VALUES ('default', 'Default', 'active', now())")
    for t in OWNED:
        op.add_column(t, sa.Column('tenant_id', sa.Integer(), nullable=True))
        # existing rows all belong to the single default tenant
        op.execute(f"UPDATE {t} SET tenant_id = (SELECT id FROM tenants WHERE slug = 'default')")
        op.alter_column(t, 'tenant_id', nullable=False)
        op.create_foreign_key(f'fk_{t}_tenant_id', t, 'tenants', ['tenant_id'], ['id'])
        op.create_index(op.f(f'ix_{t}_tenant_id'), t, ['tenant_id'])
    # email/username are unique per tenant, not globally
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_index(op.f('ix_users_username'), table_name='users')
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=False)
    op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=False)
    op.create_unique_constraint('uq_users_tenant_email', 'users', ['tenant_id', 'email'])
    op.create_unique_constraint('uq_users_tenant_username', 'users', ['tenant_id', 'username'])


def downgrade() -> None:
    op.drop_constraint('uq_users_tenant_username', 'users', type_='unique')
    op.drop_constraint('uq_users_tenant_email', 'users', type_='unique')
    op.drop_index(op.f('ix_users_username'), table_name='users')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=True)
    for t in reversed(OWNED):
        op.drop_index(op.f(f'ix_{t}_tenant_id'), table_name=t)
        op.drop_constraint(f'fk_{t}_tenant_id', t, type_='foreignkey')
        op.drop_column(t, 'tenant_id')
    op.drop_table('tenants')
