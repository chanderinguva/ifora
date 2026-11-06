"""users.public_id: opaque stable subject identifier for OIDC

Revision ID: 0014
Revises: 0013
"""
from alembic import op
import sqlalchemy as sa

revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('public_id', sa.String(36), nullable=True))
    op.execute("UPDATE users SET public_id = gen_random_uuid()::text")
    op.alter_column('users', 'public_id', nullable=False)
    op.create_unique_constraint('uq_users_public_id', 'users', ['public_id'])


def downgrade() -> None:
    op.drop_constraint('uq_users_public_id', 'users', type_='unique')
    op.drop_column('users', 'public_id')
