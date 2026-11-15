"""SAML signing keys: a staged `next` status (IFORA-25).

A staged certificate is published in the metadata before it signs, so service providers can import it ahead of the cutover.
Reversible: downgrading removes any staged keys (they never signed anything) and restores the two-status constraint.

Revision ID: 0060
Revises: 0059
"""

from alembic import op

revision = "0060"
down_revision = "0059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_saml_key_status", "saml_signing_keys", type_="check")
    op.create_check_constraint("ck_saml_key_status", "saml_signing_keys", "status IN ('active','next','retired')")


def downgrade() -> None:
    op.execute("DELETE FROM saml_signing_keys WHERE status = 'next'")
    op.drop_constraint("ck_saml_key_status", "saml_signing_keys", type_="check")
    op.create_check_constraint("ck_saml_key_status", "saml_signing_keys", "status IN ('active','retired')")
