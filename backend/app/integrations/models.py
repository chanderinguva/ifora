"""Persistence for inbound integration work."""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from backend.app.db import Base
from backend.app.tenancy import TenantOwned


class SlackIdeaCapture(TenantOwned, Base):
    __tablename__ = "slack_idea_captures"
    __table_args__ = (UniqueConstraint("tenant_id", "dedupe_key", name="uq_slack_idea_capture_event"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    dedupe_key = Column(String(300), nullable=False)
    payload = Column(JSONB, nullable=False)
    status = Column(String(20), nullable=False, default="pending", server_default="pending", index=True)
    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    next_attempt_at = Column(DateTime(timezone=True), nullable=True, index=True)
    locked_until = Column(DateTime(timezone=True), nullable=True, index=True)
    last_error = Column(Text, nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

