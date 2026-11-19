"""Self-service access requests (ADR 017)."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, SmallInteger, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB

from backend.app.db import Base
from backend.app.tenancy import TenantOwned


def _now():
    return datetime.now(timezone.utc)


class AppSelfService(TenantOwned, Base):
    """Per-application switch: may people who are not assigned ask for access? Absent row = no."""

    __tablename__ = "application_self_service"

    application_id = Column(Integer, ForeignKey("applications.id", ondelete="CASCADE"), primary_key=True)
    enabled = Column(Boolean, nullable=False, default=False)
    reason_required = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class AccessRequest(TenantOwned, Base):
    __tablename__ = "access_requests"
    __table_args__ = (
        Index("uq_access_request_pending", "user_id", "application_id", unique=True, postgresql_where=text("status = 'pending'")),
        Index("ix_access_requests_expiry", "expires_at", postgresql_where=text("status = 'approved' AND expires_at IS NOT NULL")),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    application_id = Column(Integer, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    reason = Column(String(500), nullable=True)
    status = Column(String(10), nullable=False, default="pending", index=True)  # pending | approved | denied | canceled
    decided_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    decision_note = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    # Lifecycle (IFORA-37). `routed` = created under an approval policy with stages: only that policy's approvers decide it. Rows from before
    # the policy existed stay un-routed single-stage requests that any administrator can decide.
    routed = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    stage = Column(SmallInteger, nullable=False, default=1, server_default="1")
    stages_total = Column(SmallInteger, nullable=False, default=1, server_default="1")
    duration_days = Column(Integer, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)  # set on final approval from duration_days
    escalated_at = Column(DateTime(timezone=True), nullable=True)  # the one reminder was sent
    sod_conflict = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    exception_reason = Column(String(500), nullable=True)  # why an SoD conflict was approved anyway


class ApprovalPolicy(TenantOwned, Base):
    """Per-application approval settings: allowed grant durations (days) and the pending-request timeout."""

    __tablename__ = "application_approval_policies"

    application_id = Column(Integer, ForeignKey("applications.id", ondelete="CASCADE"), primary_key=True)
    timeout_hours = Column(Integer, nullable=True)
    durations = Column(JSONB, nullable=False, default=list, server_default="[]")
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class ApprovalStage(TenantOwned, Base):
    __tablename__ = "application_approval_stages"
    __table_args__ = (UniqueConstraint("application_id", "position", name="uq_approval_stage_position"),
                      CheckConstraint("position BETWEEN 1 AND 3", name="ck_approval_stage_position"))

    id = Column(Integer, primary_key=True, autoincrement=True)
    application_id = Column(Integer, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    position = Column(SmallInteger, nullable=False)
    approver_kind = Column(String(10), nullable=False)  # owner | manager | group
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=True)


class AccessRequestDecision(TenantOwned, Base):
    __tablename__ = "access_request_decisions"
    __table_args__ = (UniqueConstraint("request_id", "stage", name="uq_access_decision_stage"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(Integer, ForeignKey("access_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    stage = Column(SmallInteger, nullable=False)
    decided_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decision = Column(String(10), nullable=False)
    note = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class SodRule(TenantOwned, Base):
    """Two applications nobody should hold at once (stored with app_a_id < app_b_id)."""

    __tablename__ = "sod_rules"
    __table_args__ = (UniqueConstraint("app_a_id", "app_b_id", name="uq_sod_rule_pair"), CheckConstraint("app_a_id < app_b_id", name="ck_sod_rule_order"))

    id = Column(Integer, primary_key=True, autoincrement=True)
    app_a_id = Column(Integer, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    app_b_id = Column(Integer, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    note = Column(String(200), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
