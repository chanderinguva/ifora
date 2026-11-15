"""IFORA-19: per-tenant issuer URL and verified domain claims.

`tenants.issuer_url` (null = derived from the slug and TENANT_BASE_DOMAIN) and `tenant_domains`, a global registry of
host names a tenant has claimed. A domain resolves to its tenant only once verified_at is set. Additive and reversible.

Revision ID: 0059
Revises: 0058
"""

import sqlalchemy as sa
from alembic import op

revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("issuer_url", sa.String(500), nullable=True))
    op.create_table(
        "tenant_domains",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("domain", sa.String(253), nullable=False),
        sa.Column("verification_token", sa.String(64), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("domain", name="uq_tenant_domains_domain"),
    )
    op.create_index("ix_tenant_domains_tenant_id", "tenant_domains", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_tenant_domains_tenant_id", table_name="tenant_domains")
    op.drop_table("tenant_domains")
    op.drop_column("tenants", "issuer_url")
