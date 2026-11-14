"""Prometheus text exposition at GET /metrics (not under /api/v1).

Off unless METRICS_TOKEN is set (then 404, so the path is not even discoverable). With a token, the scraper sends
`Authorization: Bearer <token>`; comparison is constant time. Counts are across all tenants and carry no user data:
only recipe ids / app ids as labels, never names, emails or error text.
"""

import hmac
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Tuple

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import func

from backend.app.config import settings
from backend.app.db import SessionLocal
from backend.app.tenancy import unscoped

router = APIRouter()
Sample = Tuple[str, Dict[str, str], float]


def _fmt(samples: Iterable[Sample], meta: Dict[str, Tuple[str, str]]) -> str:
    out: List[str] = []
    seen = set()
    for name, labels, value in samples:
        if name not in seen:
            seen.add(name)
            kind, help_ = meta[name]
            out += [f"# HELP {name} {help_}", f"# TYPE {name} {kind}"]
        lab = ",".join(f'{k}="{str(v).replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"' for k, v in sorted(labels.items()))
        out.append(f"{name}{{{lab}}} {value:g}" if lab else f"{name} {value:g}")
    return "\n".join(out) + "\n"


META = {
    "identityforge_recipe_jobs": ("gauge", "Live recipe jobs by status."),
    "identityforge_recipe_jobs_failed_24h": ("gauge", "Recipe jobs that failed in the last 24 hours."),
    "identityforge_recipe_queue_oldest_seconds": ("gauge", "Age of the oldest queued recipe job."),
    "identityforge_recipe_worker_up": ("gauge", "1 if a recipes worker heartbeat was seen in the last 30 seconds."),
    "identityforge_provisioning_tasks": ("gauge", "Outbound provisioning tasks by status."),
    "identityforge_provisioning_links": ("gauge", "Accounts in applications by state."),
    "identityforge_provisioning_oldest_queued_seconds": ("gauge", "Age of the oldest queued provisioning task."),
    "identityforge_users": ("gauge", "Users by status."),
    "identityforge_active_sessions": ("gauge", "Unexpired, unrevoked sessions."),
    "identityforge_ratelimit_redis_errors_total": ("counter", "Redis errors seen by the rate limiter in this API process."),
}


def collect() -> List[Sample]:
    from backend.app.provisioning.models import ProvisioningLink, ProvisioningTask
    from backend.app.recipes import engine
    from backend.app.recipes.models import RecipeJob
    from backend.app.users.model import User

    now = datetime.now(timezone.utc)
    s: List[Sample] = []
    db = SessionLocal()
    try:
        with unscoped(db):
            for st, n in db.query(RecipeJob.status, func.count()).filter(RecipeJob.mode == "live").group_by(RecipeJob.status):
                s.append(("identityforge_recipe_jobs", {"status": st}, n))
            s.append(("identityforge_recipe_jobs_failed_24h", {}, db.query(func.count(RecipeJob.id)).filter(
                RecipeJob.mode == "live", RecipeJob.status == "failed", RecipeJob.created_at > now - timedelta(hours=24)).scalar() or 0))
            oldest = db.query(func.min(RecipeJob.next_run_at)).filter(RecipeJob.mode == "live", RecipeJob.status == "queued").scalar()
            s.append(("identityforge_recipe_queue_oldest_seconds", {}, max((now - oldest).total_seconds(), 0) if oldest else 0))
            seen = engine.worker_last_seen()
            s.append(("identityforge_recipe_worker_up", {}, 1 if seen and (now - seen).total_seconds() < engine.HEARTBEAT_STALE_SECONDS else 0))
            for app_id, st, n in db.query(ProvisioningTask.app_id, ProvisioningTask.status, func.count()).group_by(ProvisioningTask.app_id, ProvisioningTask.status):
                s.append(("identityforge_provisioning_tasks", {"app_id": str(app_id), "status": st}, n))
            for app_id, st, n in db.query(ProvisioningLink.app_id, ProvisioningLink.state, func.count()).group_by(ProvisioningLink.app_id, ProvisioningLink.state):
                s.append(("identityforge_provisioning_links", {"app_id": str(app_id), "state": st}, n))
            q = db.query(func.min(ProvisioningTask.next_run_at)).filter(ProvisioningTask.status == "queued").scalar()
            s.append(("identityforge_provisioning_oldest_queued_seconds", {}, max((now - q).total_seconds(), 0) if q else 0))
            for st, n in db.query(User.status, func.count()).group_by(User.status):
                s.append(("identityforge_users", {"status": st}, n))
            from backend.app.auth.session import Session as UserSession  # noqa: WPS433

            s.append(("identityforge_active_sessions", {}, db.query(func.count(UserSession.id)).filter(
                UserSession.status == "active", UserSession.expires_at > now).scalar() or 0))
    finally:
        db.close()
    from backend.app import ratelimit

    rl = ratelimit.stats()
    s.append(("identityforge_ratelimit_redis_errors_total", {}, rl["redis_errors"]))
    return s


@router.get("/metrics", include_in_schema=False)
def metrics(request: Request):
    token = settings.METRICS_TOKEN
    if not token or len(token) < 16:
        raise HTTPException(status_code=404, detail="Not found")
    scheme, _, given = (request.headers.get("authorization") or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(given.encode(), token.encode()):
        raise HTTPException(status_code=401, detail="Unauthorized", headers={"WWW-Authenticate": "Bearer"})
    return PlainTextResponse(_fmt(collect(), META), media_type="text/plain; version=0.0.4; charset=utf-8")
