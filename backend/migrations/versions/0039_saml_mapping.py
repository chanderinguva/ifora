"""saml: NameID from username or a profile attribute

Revision ID: 0039
Revises: 0038
"""
from alembic import op
import sqlalchemy as sa

revision = '0039'
down_revision = '0038'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('saml_providers', sa.Column('name_id_attribute', sa.String(80), nullable=True))
    op.drop_constraint('ck_saml_name_id_format', 'saml_providers', type_='check')
    op.create_check_constraint('ck_saml_name_id_format', 'saml_providers', "name_id_format IN ('email','persistent','username','attribute')")


def downgrade():
    op.execute("UPDATE saml_providers SET name_id_format = 'email', name_id_attribute = NULL WHERE name_id_format IN ('username','attribute')")
    op.drop_constraint('ck_saml_name_id_format', 'saml_providers', type_='check')
    op.create_check_constraint('ck_saml_name_id_format', 'saml_providers', "name_id_format IN ('email','persistent')")
    op.drop_column('saml_providers', 'name_id_attribute')
