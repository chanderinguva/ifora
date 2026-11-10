"""application governance metadata (owner, sensitivity, review date, tags, attributes)

Revision ID: 0052
Revises: 0051
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0052'
down_revision = '0051'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('applications', sa.Column('owner_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True))
    op.create_index('ix_applications_owner_user_id', 'applications', ['owner_user_id'])
    op.add_column('applications', sa.Column('sensitivity', sa.String(8), nullable=True))
    op.add_column('applications', sa.Column('review_by', sa.Date(), nullable=True))
    op.add_column('applications', sa.Column('tags', JSONB(), nullable=False, server_default='[]'))
    op.add_column('applications', sa.Column('attributes', JSONB(), nullable=False, server_default='{}'))
    op.create_check_constraint('ck_applications_sensitivity', 'applications', "sensitivity IS NULL OR sensitivity IN ('low','medium','high')")


def downgrade():
    op.drop_constraint('ck_applications_sensitivity', 'applications')
    for c in ('attributes', 'tags', 'review_by', 'sensitivity'):
        op.drop_column('applications', c)
    op.drop_index('ix_applications_owner_user_id', 'applications')
    op.drop_column('applications', 'owner_user_id')
