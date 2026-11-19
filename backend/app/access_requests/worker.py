"""Housekeeping for access requests (IFORA-37): remove expired grants and send the one escalation reminder. Runs on the recipes worker
loop for every active tenant, like outbound provisioning; each pass is idempotent."""

from datetime import datetime, timezone
from typing import Dict, Optional

import structlog

from backend.app.access_requests import service
from backend.app.tenancy import Tenant, tenant_session, unscoped

logger = structlog.get_logger(__name__)


def process_once(at: Optional[datetime] = None) -> Dict[str, int]:
    at = at or datetime.now(timezone.utc)
    total = {"expired": 0, "reminders": 0}
    from backend.app.db import SessionLocal

    s = SessionLocal()
    try:
        with unscoped(s):
            tenant_ids = [t.id for t in s.query(Tenant).filter(Tenant.status == "active").all()]
    finally:
        s.close()
    for tid in tenant_ids:
        db = tenant_session(tid, strict=True)
        try:
            total["expired"] += service.expire_due(db, at)
            total["reminders"] += service.escalate_due(db, at)
        except Exception:  # noqa: BLE001 - one tenant must not stop the others
            db.rollback()
            logger.exception("access_requests.tenant_failed", tenant_id=tid)
        finally:
            db.close()
    return total
