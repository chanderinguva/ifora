"""Admin dashboard: things that need attention, and the trends worth glancing at. All computed live, no stored state."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.app.applications.models import Application, ApplicationAssignment
from backend.app.audit.model import AuditAction, AuditEvent
from backend.app.auth.deps import require_admin
from backend.app.db import get_db
from backend.app.provisioning.models import ProvisioningTask
from backend.app.users.model import User

router = APIRouter(prefix="/admin", tags=["dashboard"])

FAILED_LOGIN_ALERT = 10  # failed sign-ins in 24h before it becomes a task


def _task(tasks, key, severity, title, count, href):
    if count:
        tasks.append({"id": key, "severity": severity, "title": title, "count": count, "href": href})


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    now = datetime.now(timezone.utc)
    by_status = dict(db.query(User.status, func.count(User.id)).group_by(User.status).all())
    admins = db.query(User).filter(User.is_admin.is_(True), User.status == "active").all()
    no_factor = sum(1 for a in admins if not a.has_second_factor)
    failed_24h = (db.query(func.count(AuditEvent.id))
                  .filter(AuditEvent.action == AuditAction.LOGIN_FAILURE.value, AuditEvent.timestamp > now - timedelta(hours=24)).scalar())
    failed_prov = db.query(func.count(ProvisioningTask.id)).filter(ProvisioningTask.status == "failed").scalar()
    assigned = db.query(ApplicationAssignment.application_id).distinct().subquery()
    unassigned = (db.query(func.count(Application.id))
                  .filter(Application.status == "active", Application.require_assignment.is_(True), Application.sign_on_mode != "none",
                          ~Application.id.in_(db.query(assigned.c.application_id))).scalar())

    tasks: list = []
    _task(tasks, "admins_no_mfa", "high", "Administrators without a second factor", no_factor, "/admin/users")
    _task(tasks, "failed_logins", "high", "Failed sign-ins in the last 24 hours", failed_24h if failed_24h >= FAILED_LOGIN_ALERT else 0, "/admin/audit?action=LOGIN_FAILURE")
    _task(tasks, "provisioning_failed", "high", "Failed provisioning tasks", failed_prov, "/admin/app-provisioning")
    _task(tasks, "locked_out", "medium", "Locked-out users", by_status.get("locked_out", 0), "/admin/users?status=locked_out")
    _task(tasks, "password_expired", "medium", "Users with an expired password", by_status.get("password_expired", 0), "/admin/users?status=password_expired")
    _task(tasks, "apps_unassigned", "medium", "Applications nobody is assigned to", unassigned, "/admin/applications")
    _task(tasks, "awaiting_activation", "info", "Users waiting to be activated", by_status.get("staged", 0) + by_status.get("provisioned", 0), "/admin/users?status=staged")

    start = (now - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
    day = func.date_trunc("day", AuditEvent.timestamp)
    rows = (db.query(day, AuditEvent.action, func.count(AuditEvent.id))
            .filter(AuditEvent.timestamp >= start, AuditEvent.action.in_([AuditAction.LOGIN_SUCCESS.value, AuditAction.LOGIN_FAILURE.value]))
            .group_by(day, AuditEvent.action).all())
    series = {(start + timedelta(days=i)).date().isoformat(): {"date": (start + timedelta(days=i)).date().isoformat(), "success": 0, "failure": 0} for i in range(7)}
    for d, action, n in rows:
        key = d.astimezone(timezone.utc).date().isoformat()
        if key in series:
            series[key]["success" if action == AuditAction.LOGIN_SUCCESS.value else "failure"] = n

    apps_by_mode = dict(db.query(Application.sign_on_mode, func.count(Application.id)).group_by(Application.sign_on_mode).all())
    return {
        "tasks": tasks,
        "signins": list(series.values()),
        "users_by_status": by_status,
        "apps_by_mode": apps_by_mode,
        "apps_total": sum(apps_by_mode.values()),
    }
