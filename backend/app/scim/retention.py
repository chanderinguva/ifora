"""Optional hard-delete policy for users a SCIM token deprovisioned (ADR 007 S6).

Deprovisioning through SCIM only deactivates (D6). A token may carry `hard_delete_after_days`; users that token
deactivated, that nobody has touched since, and that are still inactive after that many days are deleted for good.
Administrators and anyone changed by someone else in the meantime are never deleted automatically.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import update
from sqlalchemy.orm import Session

from backend.app.audit.model import AuditAction
from backend.app.groups.model import user_group_association
from backend.app.scim import auth as scim_auth
from backend.app.scim.models import ScimDeprovisioned, ScimToken
from backend.app.tenancy import Tenant, tenant_session, unscoped
from backend.app.users.model import User

logger = structlog.get_logger(__name__)
UNTOUCHED_SLACK = timedelta(milliseconds=50)  # mark_deactivated stores the account's own final updated_at, so any later edit exceeds this


def mark_deactivated(db: Session, user: User, token: ScimToken) -> None:
    at = user.updated_at or datetime.now(timezone.utc)
    row = db.query(ScimDeprovisioned).filter(ScimDeprovisioned.user_id == user.id).first()
    if row is None:
        db.add(ScimDeprovisioned(user_id=user.id, token_id=token.id, deactivated_at=at))
    else:
        row.token_id, row.deactivated_at = token.id, at


def clear_deactivation(db: Session, user: User) -> None:
    db.query(ScimDeprovisioned).filter(ScimDeprovisioned.user_id == user.id).delete(synchronize_session=False)


def purge(db: Session, now: Optional[datetime] = None) -> int:
    """Delete due users for the tenant bound to `db`. Returns how many were deleted."""
    now = now or datetime.now(timezone.utc)
    deleted = 0
    rows = (
        db.query(ScimDeprovisioned, ScimToken)
        .join(ScimToken, ScimToken.id == ScimDeprovisioned.token_id)
        .filter(ScimToken.hard_delete_after_days.is_not(None)).all()
    )
    for row, token in rows:
        if row.deactivated_at > now - timedelta(days=token.hard_delete_after_days):
            continue
        user = db.get(User, row.user_id)
        if user is None:
            db.delete(row)
            continue
        if user.status != "inactive" or user.is_admin or user.is_super_admin:
            db.delete(row)  # reactivated or promoted since: the policy no longer applies
            continue
        if user.updated_at and user.updated_at > row.deactivated_at + UNTOUCHED_SLACK:
            db.delete(row)  # someone changed the account after the deprovisioning: keep it
            continue
        db.execute(update(user_group_association).where(user_group_association.c.added_by_user_id == user.id)
                   .values(added_by_user_id=None))
        scim_auth.audit(db, AuditAction.SCIM_USER_PURGED, None, token, user.id, "user",
                        {"email": user.email, "after_days": token.hard_delete_after_days})
        db.delete(user)
        deleted += 1
    db.commit()
    return deleted


def purge_all(now: Optional[datetime] = None) -> int:
    from backend.app.db import SessionLocal

    s = SessionLocal()
    try:
        with unscoped(s):
            tenant_ids = [t.id for t in s.query(Tenant).filter(Tenant.status == "active").all()]
    finally:
        s.close()
    total = 0
    for tid in tenant_ids:
        db = tenant_session(tid)
        try:
            total += purge(db, now)
        except Exception:  # noqa: BLE001 - one tenant must not stop the others
            db.rollback()
            logger.exception("scim.purge_failed", tenant_id=tid)
        finally:
            db.close()
    return total
