"""recipes: owners/editors, per-recipe rate limit, alert state; DB-enforced version immutability

Revision ID: 0024
Revises: 0023
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0024'
down_revision = '0023'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('recipes', sa.Column('owner_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True))
    op.add_column('recipes', sa.Column('editors', postgresql.JSONB(), nullable=False, server_default='[]'))
    op.add_column('recipes', sa.Column('rate_limit_per_hour', sa.Integer(), nullable=True))
    op.add_column('recipes', sa.Column('throttled_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('recipes', sa.Column('last_throttled_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('recipes', sa.Column('last_alert_at', sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE recipes SET owner_id = created_by WHERE owner_id IS NULL")
    # A published version is the audit record of what ran. Updates are never allowed; deletes only when the whole recipe goes
    # (the cascade runs after the recipe row is already gone, so the parent no longer exists).
    op.execute("""
        CREATE FUNCTION recipe_versions_immutable() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                RAISE EXCEPTION 'recipe versions are immutable';
            END IF;
            IF EXISTS (SELECT 1 FROM recipes WHERE id = OLD.recipe_id) THEN
                RAISE EXCEPTION 'recipe versions cannot be deleted while the recipe exists';
            END IF;
            RETURN OLD;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER recipe_versions_immutable BEFORE UPDATE OR DELETE ON recipe_versions
        FOR EACH ROW EXECUTE FUNCTION recipe_versions_immutable()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS recipe_versions_immutable ON recipe_versions")
    op.execute("DROP FUNCTION IF EXISTS recipe_versions_immutable()")
    for c in ('last_alert_at', 'last_throttled_at', 'throttled_count', 'rate_limit_per_hour', 'editors', 'owner_id'):
        op.drop_column('recipes', c)
