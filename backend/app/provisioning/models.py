"""Outbound provisioning tables (ADR 009)."""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB

from backend.app.db import Base
from backend.app.tenancy import TenantOwned


def _now():
    return datetime.now(timezone.utc)


class ProvisioningApp(TenantOwned, Base):
    """An application IdentityForge pushes users (and optionally groups) to."""

    __tablename__ = "provisioning_apps"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_provisioning_apps_tenant_name"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    public_id = Column(String(36), nullable=False, unique=True)
    name = Column(String(100), nullable=False)
    description = Column(String(500), nullable=True)
    kind = Column(String(8), nullable=False)  # scim | rest (gateway)
    base_url = Column(String(2000), nullable=False)
    auth_type = Column(String(16), nullable=False)  # bearer | basic | header
    header_name = Column(String(100), nullable=True)
    secret_enc = Column(Text, nullable=False)  # bearer token, header value, or "user:password"; never returned
    enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    options = Column(JSONB, nullable=False, default=dict)  # push_new_users, push_updates, push_groups, deactivate, update_style, user_identifier
    mapping = Column(JSONB, nullable=False, default=list)  # [{target, source}] overrides on top of the default SCIM mapping
    rest_config = Column(JSONB, nullable=True)  # gateway operations (kind = rest)
    last_test_at = Column(DateTime(timezone=True), nullable=True)
    last_test_ok = Column(Boolean, nullable=True)
    last_test_message = Column(String(300), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class ProvisioningAssignment(TenantOwned, Base):
    """A user, or every member of a group, is entitled to the app."""

    __tablename__ = "provisioning_assignments"
    __table_args__ = (
        CheckConstraint("(user_id IS NULL) <> (group_id IS NULL)", name="ck_prov_assignment_one_subject"),
        Index("uq_prov_assign_user", "app_id", "user_id", unique=True, postgresql_where=text("user_id IS NOT NULL")),
        Index("uq_prov_assign_group", "app_id", "group_id", unique=True, postgresql_where=text("group_id IS NOT NULL")),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    app_id = Column(Integer, ForeignKey("provisioning_apps.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=True, index=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class ProvisioningLink(TenantOwned, Base):
    """What the app knows about a user or group: its remote id and the last state we pushed."""

    __tablename__ = "provisioning_links"
    __table_args__ = (
        CheckConstraint("resource_type IN ('user','group')", name="ck_prov_link_type"),
        Index("uq_prov_link_user", "app_id", "user_id", unique=True, postgresql_where=text("user_id IS NOT NULL")),
        Index("uq_prov_link_group", "app_id", "group_id", unique=True, postgresql_where=text("group_id IS NOT NULL")),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    app_id = Column(Integer, ForeignKey("provisioning_apps.id", ondelete="CASCADE"), nullable=False, index=True)
    resource_type = Column(String(8), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="SET NULL"), nullable=True)
    label = Column(String(255), nullable=False, default="")  # email / group name snapshot (survives deletion of the local row)
    remote_id = Column(String(255), nullable=False)
    state = Column(String(16), nullable=False, default="synced")  # synced | deprovisioned | error
    payload_hash = Column(String(64), nullable=True)
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class ProvisioningTask(TenantOwned, Base):
    """One unit of work for the worker: bring one user or group in line with the app (idempotent reconciliation)."""

    __tablename__ = "provisioning_tasks"
    __table_args__ = (Index("ix_prov_tasks_due", "status", "next_run_at"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    app_id = Column(Integer, ForeignKey("provisioning_apps.id", ondelete="CASCADE"), nullable=False, index=True)
    resource_type = Column(String(8), nullable=False)
    user_id = Column(Integer, nullable=True)  # no foreign key: a task may outlive the row (remote delete)
    group_id = Column(Integer, nullable=True)
    link_id = Column(Integer, nullable=True)
    op = Column(String(16), nullable=False, default="sync")  # sync | delete_remote
    status = Column(String(10), nullable=False, default="queued")  # queued | running | succeeded | failed
    attempts = Column(Integer, nullable=False, default=0)
    next_run_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    locked_until = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(String(500), nullable=True)
    result = Column(String(40), nullable=True)  # created | updated | deactivated | deleted | unchanged | skipped
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    finished_at = Column(DateTime(timezone=True), nullable=True)
