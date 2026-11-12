"""Connection workspaces and one-use OAuth state; preserve existing ACLs."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("recipe_folders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("use_group_ids", JSONB(), nullable=False, server_default="[]"),
        sa.Column("manage_group_ids", JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "name", name="uq_recipe_folders_name"))
    op.create_index("ix_recipe_folders_tenant_id", "recipe_folders", ["tenant_id"])
    op.add_column("recipes", sa.Column("folder_id", sa.Integer(), sa.ForeignKey("recipe_folders.id", ondelete="RESTRICT")))
    op.create_index("ix_recipes_folder_id", "recipes", ["folder_id"])
    op.add_column("recipe_connections", sa.Column("sharing_scope", sa.String(16), nullable=False, server_default="legacy"))
    for name in ("folder_ids", "use_group_ids", "manage_group_ids"):
        op.add_column("recipe_connections", sa.Column(name, JSONB(), nullable=False, server_default="[]"))
    op.add_column("recipe_connections", sa.Column("granted_scopes", JSONB(), nullable=True))
    op.add_column("recipe_connections", sa.Column("scopes_checked_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table("connection_oauth_states",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("connection_id", sa.Integer(), sa.ForeignKey("recipe_connections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("verifier_enc", sa.Text(), nullable=False),
        sa.Column("connection_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_connection_oauth_states_tenant_id", "connection_oauth_states", ["tenant_id"])
    op.create_index("ix_connection_oauth_states_expires_at", "connection_oauth_states", ["expires_at"])


def downgrade():
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM recipe_connections WHERE sharing_scope <> 'legacy') "
               "OR EXISTS (SELECT 1 FROM recipes WHERE folder_id IS NOT NULL) THEN "
               "RAISE EXCEPTION 'Restore legacy ACLs and remove recipe folder assignments before downgrade'; END IF; END $$")
    op.drop_table("connection_oauth_states")
    for name in ("scopes_checked_at", "granted_scopes", "manage_group_ids", "use_group_ids", "folder_ids", "sharing_scope"):
        op.drop_column("recipe_connections", name)
    op.drop_column("recipes", "folder_id")
    op.drop_table("recipe_folders")
