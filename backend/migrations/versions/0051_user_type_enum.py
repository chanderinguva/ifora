"""user_type becomes a fixed list (Employee, Contingent Worker, Intern, Service Account, Test Account, Shared Account, Agent Account)

Revision ID: 0051
Revises: 0050
"""
import json

from alembic import op

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None

OPTIONS = ["Employee", "Contingent Worker", "Intern", "Service Account", "Test Account", "Shared Account", "Agent Account"]


def upgrade() -> None:
    # values already stored on users are left alone (the form shows an unknown one as-is); only the definition changes
    op.execute(
        "UPDATE profile_attributes SET data_type = 'enum', enum_options = '%s'::jsonb, "
        "description = 'Okta userType: what kind of account this is (a fixed list)' "
        "WHERE key = 'user_type' AND built_in = true" % json.dumps(OPTIONS)
    )


def downgrade() -> None:
    op.execute("UPDATE profile_attributes SET data_type = 'string', enum_options = NULL WHERE key = 'user_type' AND built_in = true")
