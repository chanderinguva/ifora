"""Provisioning worker (ADR 009 D6): claims due tasks with SKIP LOCKED, runs them, backs off on trouble.

`process_once()` handles everything currently due for every tenant and returns; the recipes worker loop calls it, and
several workers may run at once.
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import structlog
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.config import settings
from backend.app.provisioning import adapters, service
from backend.app.provisioning.models import ProvisioningApp, ProvisioningLink, ProvisioningTask
from backend.app.recipes import crypto
from backend.app.tenancy import Tenant, tenant_session, unscoped

logger = structlog.get_logger(__name__)
BACKOFF_CAP = 600
KEEP_OK_DAYS, KEEP_FAILED_DAYS = 7, 30


def backoff(attempt: int) -> int:
    return min(15 * (2 ** max(attempt - 1, 0)), BACKOFF_CAP)


def claim(db: Session, at: datetime) -> List[int]:
    rows = (
        db.query(ProvisioningTask)
        .filter(or_(and_(ProvisioningTask.status == "queued", ProvisioningTask.next_run_at <= at),
                    and_(ProvisioningTask.status == "running", ProvisioningTask.locked_until < at)))
        .order_by(ProvisioningTask.id).with_for_update(skip_locked=True).limit(settings.PROVISIONING_BATCH * 4).all()
    )
    per_app: Dict[int, int] = {}
    ids: List[int] = []
    for t in rows:
        if len(ids) >= settings.PROVISIONING_BATCH or per_app.get(t.app_id, 0) >= settings.PROVISIONING_PER_APP_BATCH:
            continue
        per_app[t.app_id] = per_app.get(t.app_id, 0) + 1
        t.status, t.locked_until = "running", at + timedelta(seconds=settings.PROVISIONING_LEASE_SECONDS)
        ids.append(t.id)
    db.commit()
    return ids


def _fail_link(db: Session, task: ProvisioningTask, message: str) -> None:
    q = db.query(ProvisioningLink).filter(ProvisioningLink.app_id == task.app_id)
    link = (q.filter(ProvisioningLink.user_id == task.user_id).first() if task.user_id is not None
            else q.filter(ProvisioningLink.group_id == task.group_id).first() if task.group_id is not None else None)
    if link is not None:
        link.state, link.last_error = "error", message[:500]


def run_task(db: Session, task_id: int, at: datetime) -> str:
    task = db.get(ProvisioningTask, task_id)
    if task is None or task.status != "running":
        return "gone"
    app = db.get(ProvisioningApp, task.app_id)
    try:
        if app is None or not app.enabled:
            task.status, task.result, task.finished_at = "succeeded", "skipped", at
            db.commit()
            return "skipped"
        ad = adapters.build(app, crypto.decrypt(app.secret_enc))
        if task.op == "delete_remote":
            result = service.delete_remote(db, app, ad, task.link_id)
        elif task.resource_type == "group":
            result = service.sync_group(db, app, ad, task.group_id)
        else:
            result = service.sync_user(db, app, ad, task.user_id)
            if result in ("created", "linked", "deactivated", "deleted", "reactivated"):
                service.queue_groups_for_user(db, app, task.user_id)
        task.status, task.result, task.last_error, task.finished_at = "succeeded", result, None, at
        task.attempts += 1
        db.commit()
        return result
    except adapters.Retryable as e:
        db.rollback()
        task = db.get(ProvisioningTask, task_id)
        task.attempts += 1
        task.last_error = str(e)[:500]
        if task.attempts >= settings.PROVISIONING_MAX_ATTEMPTS:
            task.status, task.finished_at = "failed", at
            _fail_link(db, task, str(e))
            _audit_failure(db, app, task)
        else:
            wait = max(backoff(task.attempts), getattr(e, "retry_after", None) or 0)
            task.status, task.next_run_at, task.locked_until = "queued", at + timedelta(seconds=min(wait, 3600)), None
        db.commit()
        return "retry"
    except (adapters.Permanent, crypto.RecipeKeyError) as e:
        db.rollback()
        task = db.get(ProvisioningTask, task_id)
        task.attempts += 1
        task.status, task.last_error, task.finished_at = "failed", str(e)[:500], at
        _fail_link(db, task, str(e))
        _audit_failure(db, app, task)
        db.commit()
        return "failed"
    except Exception as e:  # noqa: BLE001 - a bug in one task must not stop the batch
        db.rollback()
        logger.exception("provisioning.task_crashed", task_id=task_id)
        task = db.get(ProvisioningTask, task_id)
        task.attempts += 1
        task.status, task.last_error, task.finished_at = "failed", f"internal error: {type(e).__name__}", at
        db.commit()
        return "failed"


def _audit_failure(db: Session, app: Optional[ProvisioningApp], task: ProvisioningTask) -> None:
    record(db, AuditAction.PROVISIONING_TASK_FAILED, None, None, task.app_id, "provisioning_app",
           {"app": app.name if app else None, "resource": task.resource_type, "user_id": task.user_id,
            "group_id": task.group_id, "error": (task.last_error or "")[:200]})


def prune(db: Session, at: datetime) -> None:
    db.query(ProvisioningTask).filter(ProvisioningTask.status == "succeeded", ProvisioningTask.finished_at < at - timedelta(days=KEEP_OK_DAYS)).delete(synchronize_session=False)
    db.query(ProvisioningTask).filter(ProvisioningTask.status == "failed", ProvisioningTask.finished_at < at - timedelta(days=KEEP_FAILED_DAYS)).delete(synchronize_session=False)


def process_tenant(db: Session, at: datetime) -> Dict[str, int]:
    stats = {"swept": service.sweep_orphans(db), "ran": 0}
    db.commit()
    for tid in claim(db, at):
        run_task(db, tid, at)
        stats["ran"] += 1
    prune(db, at)
    db.commit()
    return stats


def process_once(at: Optional[datetime] = None) -> Dict[str, int]:
    at = at or datetime.now(timezone.utc)
    total = {"swept": 0, "ran": 0}
    if not settings.PROVISIONING_ENABLED:
        return total
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
            for k, v in process_tenant(db, at).items():
                total[k] += v
        except Exception:  # noqa: BLE001 - one tenant must not stop the others
            db.rollback()
            logger.exception("provisioning.tenant_failed", tenant_id=tid)
        finally:
            db.close()
    return total
