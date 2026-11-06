"""recipe engine: recipes, versions, connections, outbox, jobs, job steps (ADR 008)

Revision ID: 0017
Revises: 0016
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0017'
down_revision = '0016'
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())


def _tenant():
    return sa.Column('tenant_id', sa.Integer(), nullable=False)


def upgrade() -> None:
    op.create_table(
        'recipes',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        _tenant(),
        sa.Column('public_id', sa.String(length=32), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('draft', JSONB, nullable=False),
        sa.Column('published_version', sa.Integer(), nullable=True),
        sa.Column('published_trigger_type', sa.String(length=40), nullable=True),
        sa.Column('webhook_secret_enc', sa.Text(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', TS, nullable=False),
        sa.Column('updated_at', TS, nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('public_id'),
        sa.UniqueConstraint('tenant_id', 'name', name='uq_recipes_tenant_name'),
    )
    op.create_index(op.f('ix_recipes_tenant_id'), 'recipes', ['tenant_id'])
    op.create_index(op.f('ix_recipes_published_trigger_type'), 'recipes', ['published_trigger_type'])

    op.create_table(
        'recipe_versions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        _tenant(),
        sa.Column('recipe_id', sa.Integer(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('definition', JSONB, nullable=False),
        sa.Column('published_by', sa.Integer(), nullable=True),
        sa.Column('published_at', TS, nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['recipe_id'], ['recipes.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['published_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('recipe_id', 'version', name='uq_recipe_versions_recipe_version'),
    )
    op.create_index(op.f('ix_recipe_versions_tenant_id'), 'recipe_versions', ['tenant_id'])
    op.create_index(op.f('ix_recipe_versions_recipe_id'), 'recipe_versions', ['recipe_id'])

    op.create_table(
        'recipe_connections',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        _tenant(),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('header_name', sa.String(length=100), nullable=True),
        sa.Column('allowed_host', sa.String(length=255), nullable=False),
        sa.Column('secret_enc', sa.Text(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', TS, nullable=False),
        sa.Column('updated_at', TS, nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'name', name='uq_recipe_connections_tenant_name'),
    )
    op.create_index(op.f('ix_recipe_connections_tenant_id'), 'recipe_connections', ['tenant_id'])

    op.create_table(
        'recipe_outbox',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        _tenant(),
        sa.Column('event_type', sa.String(length=40), nullable=False),
        sa.Column('payload', JSONB, nullable=False),
        sa.Column('depth', sa.Integer(), nullable=False),
        sa.Column('origin_recipe_id', sa.Integer(), nullable=True),
        sa.Column('created_at', TS, nullable=False),
        sa.Column('dispatched_at', TS, nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_recipe_outbox_tenant_id'), 'recipe_outbox', ['tenant_id'])
    op.create_index(op.f('ix_recipe_outbox_dispatched_at'), 'recipe_outbox', ['dispatched_at'])

    op.create_table(
        'recipe_jobs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        _tenant(),
        sa.Column('recipe_id', sa.Integer(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=True),
        sa.Column('mode', sa.String(length=10), nullable=False),
        sa.Column('status', sa.String(length=12), nullable=False),
        sa.Column('definition', JSONB, nullable=False),
        sa.Column('trigger', JSONB, nullable=False),
        sa.Column('trigger_type', sa.String(length=40), nullable=False),
        sa.Column('event_id', sa.Integer(), nullable=True),
        sa.Column('idempotency_key', sa.String(length=128), nullable=False),
        sa.Column('depth', sa.Integer(), nullable=False),
        sa.Column('pc', sa.Integer(), nullable=False),
        sa.Column('executed_steps', sa.Integer(), nullable=False),
        sa.Column('attempt', sa.Integer(), nullable=False),
        sa.Column('step_outputs', JSONB, nullable=False),
        sa.Column('next_run_at', TS, nullable=False),
        sa.Column('locked_until', TS, nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', TS, nullable=False),
        sa.Column('started_at', TS, nullable=True),
        sa.Column('finished_at', TS, nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['recipe_id'], ['recipes.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('recipe_id', 'idempotency_key', name='uq_recipe_jobs_idempotency'),
    )
    op.create_index(op.f('ix_recipe_jobs_tenant_id'), 'recipe_jobs', ['tenant_id'])
    op.create_index(op.f('ix_recipe_jobs_recipe_id'), 'recipe_jobs', ['recipe_id'])
    op.create_index(op.f('ix_recipe_jobs_status'), 'recipe_jobs', ['status'])

    op.create_table(
        'recipe_job_steps',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        _tenant(),
        sa.Column('job_id', sa.Integer(), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('step_id', sa.String(length=64), nullable=False),
        sa.Column('type', sa.String(length=30), nullable=False),
        sa.Column('status', sa.String(length=12), nullable=False),
        sa.Column('attempt', sa.Integer(), nullable=False),
        sa.Column('input', JSONB, nullable=True),
        sa.Column('output', JSONB, nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('started_at', TS, nullable=False),
        sa.Column('finished_at', TS, nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['job_id'], ['recipe_jobs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_recipe_job_steps_tenant_id'), 'recipe_job_steps', ['tenant_id'])
    op.create_index(op.f('ix_recipe_job_steps_job_id'), 'recipe_job_steps', ['job_id'])


def downgrade() -> None:
    for table in ('recipe_job_steps', 'recipe_jobs', 'recipe_outbox', 'recipe_connections', 'recipe_versions', 'recipes'):
        op.drop_table(table)
