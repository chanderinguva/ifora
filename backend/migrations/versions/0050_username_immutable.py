"""users.username is assigned once: a trigger refuses any change (defence in depth next to the ORM guard)

Revision ID: 0050
Revises: 0049
"""
from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION users_username_immutable() RETURNS trigger AS $$
        BEGIN
            IF NEW.username IS DISTINCT FROM OLD.username THEN
                RAISE EXCEPTION 'users.username is immutable' USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_users_username_immutable BEFORE UPDATE OF username ON users
        FOR EACH ROW EXECUTE FUNCTION users_username_immutable()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_users_username_immutable ON users")
    op.execute("DROP FUNCTION IF EXISTS users_username_immutable()")
