"""group membership: tenant_id, filled and enforced by a trigger

The membership table had no tenant column, so isolation relied on the group and user rows alone. Now every row
carries its tenant, copied from the group on insert, and an insert that would link a user and a group of different
tenants is refused by the database.

Revision ID: 0030
Revises: 0029
"""
from alembic import op
import sqlalchemy as sa

revision = '0030'
down_revision = '0029'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('user_group_membership', sa.Column('tenant_id', sa.Integer(), nullable=True))
    op.execute("UPDATE user_group_membership m SET tenant_id = g.tenant_id FROM groups g WHERE g.id = m.group_id")
    op.alter_column('user_group_membership', 'tenant_id', nullable=False)
    op.create_foreign_key('fk_membership_tenant', 'user_group_membership', 'tenants', ['tenant_id'], ['id'])
    op.create_index('ix_user_group_membership_tenant_id', 'user_group_membership', ['tenant_id'])
    op.execute("""
        CREATE OR REPLACE FUNCTION membership_tenant_guard() RETURNS trigger AS $$
        DECLARE g_tenant integer; u_tenant integer;
        BEGIN
            SELECT tenant_id INTO g_tenant FROM groups WHERE id = NEW.group_id;
            SELECT tenant_id INTO u_tenant FROM users WHERE id = NEW.user_id;
            IF g_tenant IS NULL OR u_tenant IS NULL OR g_tenant <> u_tenant THEN
                RAISE EXCEPTION 'group membership must link a user and a group of the same tenant';
            END IF;
            NEW.tenant_id := g_tenant;
            RETURN NEW;
        END $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER membership_tenant_guard BEFORE INSERT OR UPDATE ON user_group_membership
        FOR EACH ROW EXECUTE FUNCTION membership_tenant_guard();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS membership_tenant_guard ON user_group_membership")
    op.execute("DROP FUNCTION IF EXISTS membership_tenant_guard()")
    op.drop_index('ix_user_group_membership_tenant_id', table_name='user_group_membership')
    op.drop_constraint('fk_membership_tenant', 'user_group_membership', type_='foreignkey')
    op.drop_column('user_group_membership', 'tenant_id')
