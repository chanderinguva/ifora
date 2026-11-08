"""applications: unified app object, shared assignments; links from OIDC clients and provisioning apps

Revision ID: 0035
Revises: 0034
"""
import uuid

from alembic import op
import sqlalchemy as sa

revision = '0035'
down_revision = '0034'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'applications',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False, index=True),
        sa.Column('public_id', sa.String(36), nullable=False, unique=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.String(500)),
        sa.Column('sign_on_mode', sa.String(16), nullable=False, server_default='none'),
        sa.Column('launch_url', sa.String(2000)),
        sa.Column('status', sa.String(10), nullable=False, server_default='active'),
        sa.Column('visible', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('require_assignment', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('tenant_id', 'name', name='uq_applications_tenant_name'),
        sa.CheckConstraint("sign_on_mode IN ('none','bookmark','oidc')", name='ck_applications_sign_on_mode'),
        sa.CheckConstraint("status IN ('active','inactive')", name='ck_applications_status'),
    )
    op.create_table(
        'application_assignments',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False, index=True),
        sa.Column('application_id', sa.Integer(), sa.ForeignKey('applications.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), index=True),
        sa.Column('group_id', sa.Integer(), sa.ForeignKey('groups.id', ondelete='CASCADE'), index=True),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('(user_id IS NULL) <> (group_id IS NULL)', name='ck_app_assignment_one_subject'),
    )
    op.create_index('uq_app_assign_user', 'application_assignments', ['application_id', 'user_id'], unique=True, postgresql_where=sa.text('user_id IS NOT NULL'))
    op.create_index('uq_app_assign_group', 'application_assignments', ['application_id', 'group_id'], unique=True, postgresql_where=sa.text('group_id IS NOT NULL'))
    op.add_column('oidc_clients', sa.Column('application_id', sa.Integer(), sa.ForeignKey('applications.id', ondelete='SET NULL')))
    op.create_index('uq_oidc_clients_application', 'oidc_clients', ['application_id'], unique=True, postgresql_where=sa.text('application_id IS NOT NULL'))
    op.add_column('provisioning_apps', sa.Column('application_id', sa.Integer(), sa.ForeignKey('applications.id', ondelete='RESTRICT')))

    bind = op.get_bind()
    now = sa.text("now()")

    def unique_name(tenant_id, wanted, taken):
        name, n = wanted, 1
        while (tenant_id, name) in taken:
            n += 1
            name = f"{wanted[:90]} ({n})"
        taken.add((tenant_id, name))
        return name

    taken = set()
    # every existing provisioning app becomes an application with no sign-on; its assignments move across
    for row in bind.execute(sa.text("SELECT id, tenant_id, name, description, created_by FROM provisioning_apps ORDER BY id")).fetchall():
        name = unique_name(row.tenant_id, row.name, taken)
        app_id = bind.execute(sa.text(
            "INSERT INTO applications (tenant_id, public_id, name, description, sign_on_mode, status, visible, require_assignment, created_by, created_at, updated_at) "
            "VALUES (:t, :p, :n, :d, 'none', 'active', false, false, :c, now(), now()) RETURNING id"),
            {"t": row.tenant_id, "p": str(uuid.uuid4()), "n": name, "d": row.description, "c": row.created_by}).scalar()
        bind.execute(sa.text("UPDATE provisioning_apps SET application_id = :a WHERE id = :i"), {"a": app_id, "i": row.id})
        bind.execute(sa.text(
            "INSERT INTO application_assignments (tenant_id, application_id, user_id, group_id, created_by, created_at) "
            "SELECT tenant_id, :a, user_id, group_id, created_by, created_at FROM provisioning_assignments WHERE app_id = :i"),
            {"a": app_id, "i": row.id})
    # every OIDC client becomes an OIDC application. Existing behaviour is kept: assignment is not required for them
    for row in bind.execute(sa.text("SELECT id, tenant_id, name, description, client_type, status, created_by FROM oidc_clients ORDER BY id")).fetchall():
        name = unique_name(row.tenant_id, row.name, taken)
        app_id = bind.execute(sa.text(
            "INSERT INTO applications (tenant_id, public_id, name, description, sign_on_mode, status, visible, require_assignment, created_by, created_at, updated_at) "
            "VALUES (:t, :p, :n, :d, 'oidc', :s, :v, false, :c, now(), now()) RETURNING id"),
            {"t": row.tenant_id, "p": str(uuid.uuid4()), "n": name, "d": row.description,
             "s": "active" if row.status == "active" else "inactive", "v": row.client_type != "service", "c": row.created_by}).scalar()
        bind.execute(sa.text("UPDATE oidc_clients SET application_id = :a WHERE id = :i"), {"a": app_id, "i": row.id})

    op.alter_column('provisioning_apps', 'application_id', nullable=False)
    op.create_index('uq_provisioning_apps_application', 'provisioning_apps', ['application_id'], unique=True)
    op.drop_table('provisioning_assignments')


def downgrade() -> None:
    op.create_table(
        'provisioning_assignments',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False, index=True),
        sa.Column('app_id', sa.Integer(), sa.ForeignKey('provisioning_apps.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), index=True),
        sa.Column('group_id', sa.Integer(), sa.ForeignKey('groups.id', ondelete='CASCADE'), index=True),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('(user_id IS NULL) <> (group_id IS NULL)', name='ck_prov_assignment_one_subject'),
    )
    op.create_index('uq_prov_assign_user', 'provisioning_assignments', ['app_id', 'user_id'], unique=True, postgresql_where=sa.text('user_id IS NOT NULL'))
    op.create_index('uq_prov_assign_group', 'provisioning_assignments', ['app_id', 'group_id'], unique=True, postgresql_where=sa.text('group_id IS NOT NULL'))
    op.get_bind().execute(sa.text(
        "INSERT INTO provisioning_assignments (tenant_id, app_id, user_id, group_id, created_by, created_at) "
        "SELECT a.tenant_id, p.id, a.user_id, a.group_id, a.created_by, a.created_at "
        "FROM application_assignments a JOIN provisioning_apps p ON p.application_id = a.application_id"))
    op.drop_index('uq_provisioning_apps_application', table_name='provisioning_apps')
    op.drop_column('provisioning_apps', 'application_id')
    op.drop_index('uq_oidc_clients_application', table_name='oidc_clients')
    op.drop_column('oidc_clients', 'application_id')
    op.drop_table('application_assignments')
    op.drop_table('applications')
