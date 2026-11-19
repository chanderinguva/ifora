"""Push sign-in approval with number matching (IFORA-77): enrolled devices, per-login challenges and the policy switches.

Off by default for everyone; nothing changes until an administrator configures VAPID keys and turns it on. Reversible.

Revision ID: 0066
Revises: 0065
"""

import sqlalchemy as sa
from alembic import op

revision = "0066"
down_revision = "0065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "push_devices",
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("endpoint_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("secret_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "push_challenges",
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("mfa_challenge_id", sa.Integer(), sa.ForeignKey("mfa_challenges.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("number", sa.String(2), nullable=False),
        sa.Column("choices", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("requested_ip", sa.String(64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.add_column("org_security_policy", sa.Column("push_members", sa.String(10), nullable=False, server_default="off"))
    op.add_column("org_security_policy", sa.Column("push_admins", sa.String(10), nullable=False, server_default="off"))
    op.create_check_constraint("ck_org_policy_push_members", "org_security_policy", "push_members IN ('off','allowed')")
    op.create_check_constraint("ck_org_policy_push_admins", "org_security_policy", "push_admins IN ('off','allowed','required')")


def downgrade() -> None:
    op.drop_constraint("ck_org_policy_push_admins", "org_security_policy")
    op.drop_constraint("ck_org_policy_push_members", "org_security_policy")
    op.drop_column("org_security_policy", "push_admins")
    op.drop_column("org_security_policy", "push_members")
    op.drop_table("push_challenges")
    op.drop_table("push_devices")
