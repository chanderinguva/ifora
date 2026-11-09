"""lookup tables for recipes (ADR 021 section 2)

Revision ID: 0048
Revises: 0047
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0048'
down_revision = '0047'
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        'lookup_tables',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=40), nullable=False),
        sa.Column('description', sa.String(length=300), nullable=True),
        sa.Column('columns', JSONB, nullable=False),
        sa.Column('key_column', sa.String(length=40), nullable=True),
        sa.Column('admin_managed', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('row_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', TS, nullable=False),
        sa.Column('updated_at', TS, nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'name', name='uq_lookup_tables_tenant_name'),
    )
    op.create_index(op.f('ix_lookup_tables_tenant_id'), 'lookup_tables', ['tenant_id'])
    op.create_table(
        'lookup_rows',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('table_id', sa.Integer(), nullable=False),
        sa.Column('data', JSONB, nullable=False),
        sa.Column('key_value', sa.String(length=500), nullable=True),
        sa.Column('updated_at', TS, nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['table_id'], ['lookup_tables.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_lookup_rows_tenant_id'), 'lookup_rows', ['tenant_id'])
    op.create_index(op.f('ix_lookup_rows_table_id'), 'lookup_rows', ['table_id'])
    op.create_index('uq_lookup_rows_key', 'lookup_rows', ['table_id', 'key_value'], unique=True,
                    postgresql_where=sa.text('key_value IS NOT NULL'))


def downgrade() -> None:
    op.drop_table('lookup_rows')
    op.drop_table('lookup_tables')
