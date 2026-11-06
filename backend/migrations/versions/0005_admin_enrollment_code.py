"""one-time enrolment code for admins' first factor

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('enrollment_code_hash', sa.String(length=64), nullable=True))
    op.add_column('users', sa.Column('enrollment_code_expires_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'enrollment_code_expires_at')
    op.drop_column('users', 'enrollment_code_hash')
