"""Which first-run checklist items an administrator has dismissed (IFORA-42). Completion itself is never stored."""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint

from backend.app.db import Base
from backend.app.tenancy import TenantOwned


def _now():
    return datetime.now(timezone.utc)


class ChecklistDismissal(TenantOwned, Base):
    __tablename__ = "setup_checklist_dismissals"
    __table_args__ = (UniqueConstraint("user_id", "item", name="uq_setup_checklist_dismissals_item"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    item = Column(String(40), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
