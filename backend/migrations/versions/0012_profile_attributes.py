"""profile attribute catalog (Profile editor)

Revision ID: 0012
Revises: 0011
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None

# key, display name, type, user editable, description  (kept in sync with profiles/catalog.py DEFAULTS)
SEED = [
    ("title", "Title", "string", True, "Job title"),
    ("phone", "Phone", "string", True, "Contact phone number"),
    ("location", "Location", "string", True, "Office or city"),
    ("bio", "Bio", "string", True, "A few words about you"),
    ("timezone", "Time zone", "timezone", True, "Used to display dates and times"),
    ("locale", "Locale", "locale", True, "Date and number formats"),
    ("department", "Department", "string", False, "Managed by administrators"),
    ("employee_id", "Employee ID", "string", False, "Managed by administrators"),
    ("manager", "Manager", "string", False, "Managed by administrators"),
    ("cost_center", "Cost center", "string", False, "Managed by administrators"),
]


def upgrade() -> None:
    op.create_table(
        'profile_attributes',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=50), nullable=False),
        sa.Column('display_name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('data_type', sa.String(length=16), nullable=False),
        sa.Column('enum_options', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('user_editable', sa.Boolean(), nullable=False),
        sa.Column('built_in', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'key', name='uq_profile_attributes_tenant_key'),
    )
    op.create_index(op.f('ix_profile_attributes_tenant_id'), 'profile_attributes', ['tenant_id'])
    bind = op.get_bind()
    tid = bind.execute(sa.text("SELECT id FROM tenants WHERE slug = 'default'")).scalar()
    if tid is not None:
        for i, (key, name, typ, editable, desc) in enumerate(SEED):
            bind.execute(sa.text(
                "INSERT INTO profile_attributes (tenant_id, key, display_name, description, data_type, user_editable, built_in, sort_order, created_at) "
                "VALUES (:t, :k, :n, :d, :ty, :e, true, :o, now())"
            ), {"t": tid, "k": key, "n": name, "d": desc, "ty": typ, "e": editable, "o": i})


def downgrade() -> None:
    op.drop_index(op.f('ix_profile_attributes_tenant_id'), table_name='profile_attributes')
    op.drop_table('profile_attributes')
