"""Email one-time code as a second factor (IFORA-60): per-user state and the per-audience policy switches.

Off by default for everyone (a fail-safe default): nothing changes until an administrator turns it on. Reversible.

Revision ID: 0065
Revises: 0064
"""

import sqlalchemy as sa
from alembic import op

revision = "0065"
down_revision = "0064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_email_otp",
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("code_hash", sa.String(64), nullable=True),
        sa.Column("code_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.add_column("org_security_policy", sa.Column("email_otp_members", sa.String(10), nullable=False, server_default="off"))
    op.add_column("org_security_policy", sa.Column("email_otp_admins", sa.String(10), nullable=False, server_default="off"))
    op.create_check_constraint("ck_org_policy_email_otp_members", "org_security_policy", "email_otp_members IN ('off','allowed')")
    op.create_check_constraint("ck_org_policy_email_otp_admins", "org_security_policy", "email_otp_admins IN ('off','allowed','required')")


def downgrade() -> None:
    op.drop_constraint("ck_org_policy_email_otp_admins", "org_security_policy")
    op.drop_constraint("ck_org_policy_email_otp_members", "org_security_policy")
    op.drop_column("org_security_policy", "email_otp_admins")
    op.drop_column("org_security_policy", "email_otp_members")
    op.drop_table("user_email_otp")
