"""Stored credentials of users who are no longer entitled to the application (unassigned, removed from the group) are deleted."""

from sqlalchemy import delete
from sqlalchemy.orm import Session

from backend.app.applications.entitlement import entitled_user_ids
from backend.app.swa.models import SwaCredential


def purge_unentitled(db: Session) -> int:
    """Caller provides the (unscoped) session and commits."""
    n = 0
    for (app_id,) in db.query(SwaCredential.application_id).distinct().all():
        keep = entitled_user_ids(db, app_id)
        stmt = delete(SwaCredential).where(SwaCredential.application_id == app_id)
        if keep:
            stmt = stmt.where(SwaCredential.user_id.not_in(keep))
        n += db.execute(stmt).rowcount
    return n
