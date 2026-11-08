"""Entitlement, task queueing and reconciliation (ADR 009 D2, D6).

A user is *entitled* to an app when assigned directly or through a group. The desired state of (app, user) is
"present and active" iff entitled AND the user's status is `active`; anything else means deprovision per the app's
policy. Every task is an idempotent "make the app match IdentityForge" for one user or group, so repeated, late or
duplicated tasks are harmless.
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Set

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.groups.model import Group, user_group_association as membership
from backend.app.provisioning import adapters, mapping
from backend.app.provisioning.models import ProvisioningApp, ProvisioningAssignment, ProvisioningLink, ProvisioningTask
from backend.app.users.model import User

logger = structlog.get_logger(__name__)

DEFAULT_OPTIONS = {
    "push_new_users": True,      # create users in the app when they become entitled
    "push_updates": True,        # push profile changes
    "push_groups": False,        # also create/update the groups assigned to the app (SCIM Groups)
    "deactivate": "patch",       # when no longer entitled: patch (active=false) | delete | none
    "update_style": "put",       # SCIM updates: put | patch
    "user_identifier": "email",  # what goes into userName: email | username
}
DEACTIVATE_MODES = ("patch", "delete", "none")


def now() -> datetime:
    return datetime.now(timezone.utc)


def options_of(app: ProvisioningApp) -> dict:
    return {**DEFAULT_OPTIONS, **(app.options or {})}


# ---- entitlement ---------------------------------------------------------------------------------------------

def assigned_group_ids(db: Session, app_id: int) -> List[int]:
    return [g for (g,) in db.query(ProvisioningAssignment.group_id).filter(
        ProvisioningAssignment.app_id == app_id, ProvisioningAssignment.group_id.is_not(None)).all()]


def is_entitled(db: Session, app: ProvisioningApp, user_id: int) -> bool:
    if db.query(ProvisioningAssignment.id).filter(
            ProvisioningAssignment.app_id == app.id, ProvisioningAssignment.user_id == user_id).first():
        return True
    gids = assigned_group_ids(db, app.id)
    if not gids:
        return False
    return db.execute(select(membership.c.user_id).where(membership.c.user_id == user_id, membership.c.group_id.in_(gids)).limit(1)).first() is not None


def entitled_user_ids(db: Session, app: ProvisioningApp) -> Set[int]:
    ids = {u for (u,) in db.query(ProvisioningAssignment.user_id).filter(
        ProvisioningAssignment.app_id == app.id, ProvisioningAssignment.user_id.is_not(None)).all()}
    gids = assigned_group_ids(db, app.id)
    if gids:
        ids |= {u for (u,) in db.execute(select(membership.c.user_id).where(membership.c.group_id.in_(gids))).all()}
    return ids


def group_members(db: Session, group_id: int) -> List[int]:
    return [u for (u,) in db.execute(select(membership.c.user_id).where(membership.c.group_id == group_id)).all()]


# ---- queueing -------------------------------------------------------------------------------------------------

def _enabled_apps(db: Session) -> List[ProvisioningApp]:
    return db.query(ProvisioningApp).filter(ProvisioningApp.enabled.is_(True)).all()


def queue(db: Session, app_id: int, resource_type: str, *, user_id: Optional[int] = None, group_id: Optional[int] = None,
          op: str = "sync", link_id: Optional[int] = None) -> bool:
    """Add a task unless an identical one is already waiting (coalescing). Caller commits."""
    q = db.query(ProvisioningTask.id).filter(
        ProvisioningTask.app_id == app_id, ProvisioningTask.resource_type == resource_type,
        ProvisioningTask.op == op, ProvisioningTask.status == "queued",
        ProvisioningTask.user_id.is_(user_id) if user_id is None else ProvisioningTask.user_id == user_id,
        ProvisioningTask.group_id.is_(group_id) if group_id is None else ProvisioningTask.group_id == group_id)
    if q.first():
        return False
    db.add(ProvisioningTask(app_id=app_id, resource_type=resource_type, user_id=user_id, group_id=group_id, op=op,
                            link_id=link_id, status="queued", next_run_at=now(), created_at=now()))
    return True


def queue_user(db: Session, user_id: int, apps: Optional[Iterable[ProvisioningApp]] = None) -> int:
    n = 0
    for app in (apps if apps is not None else _enabled_apps(db)):
        has_link = db.query(ProvisioningLink.id).filter(ProvisioningLink.app_id == app.id, ProvisioningLink.user_id == user_id).first()
        if has_link or is_entitled(db, app, user_id):
            n += queue(db, app.id, "user", user_id=user_id)
    return n


def queue_groups_for_user(db: Session, app: ProvisioningApp, user_id: int) -> None:
    if not options_of(app)["push_groups"]:
        return
    for gid in assigned_group_ids(db, app.id):
        if db.execute(select(membership.c.user_id).where(membership.c.user_id == user_id, membership.c.group_id == gid)).first():
            queue(db, app.id, "group", group_id=gid)


def queue_group(db: Session, group_id: int) -> None:
    """A group's name or membership changed: refresh it in every app it is assigned to."""
    for app in _enabled_apps(db):
        if db.query(ProvisioningAssignment.id).filter(ProvisioningAssignment.app_id == app.id, ProvisioningAssignment.group_id == group_id).first():
            if options_of(app)["push_groups"]:
                queue(db, app.id, "group", group_id=group_id)


def queue_full_sync(db: Session, app: ProvisioningApp) -> Dict[str, int]:
    """Re-check everyone entitled, everyone already linked (to deprovision), and every assigned group."""
    users = entitled_user_ids(db, app) | {u for (u,) in db.query(ProvisioningLink.user_id).filter(
        ProvisioningLink.app_id == app.id, ProvisioningLink.user_id.is_not(None), ProvisioningLink.resource_type == "user").all()}
    n_users = sum(queue(db, app.id, "user", user_id=u) for u in users)
    n_groups = 0
    if options_of(app)["push_groups"]:
        gids = set(assigned_group_ids(db, app.id)) | {g for (g,) in db.query(ProvisioningLink.group_id).filter(
            ProvisioningLink.app_id == app.id, ProvisioningLink.group_id.is_not(None)).all()}
        n_groups = sum(queue(db, app.id, "group", group_id=g) for g in gids)
    return {"users": n_users, "groups": n_groups}


_USER_ACTIONS = {"USER_CREATED", "USER_UPDATED", "USER_ACTIVATED", "USER_DEACTIVATED", "USER_STATUS_CHANGED", "PROFILE_UPDATED",
                 "SCIM_USER_CREATED", "SCIM_USER_UPDATED", "SCIM_USER_DEACTIVATED", "SCIM_USER_ACTIVATED"}
_MEMBER_ACTIONS = {"GROUP_MEMBER_ADDED", "GROUP_MEMBER_REMOVED", "SCIM_GROUP_MEMBER_ADDED", "SCIM_GROUP_MEMBER_REMOVED"}
_GROUP_ACTIONS = {"GROUP_UPDATED", "SCIM_GROUP_UPDATED"}


def on_audit(db: Session, action, target_id, metadata: Optional[dict]) -> None:
    """Called by `audit.service.record()` for every audit row, in the caller's transaction (like the recipe outbox)."""
    name = getattr(action, "value", str(action))
    if name not in _USER_ACTIONS and name not in _MEMBER_ACTIONS and name not in _GROUP_ACTIONS:
        return
    try:
        apps = _enabled_apps(db)
        if not apps or target_id is None:
            return
        tid = int(target_id)
        if name in _USER_ACTIONS:
            queue_user(db, tid, apps)
        elif name in _MEMBER_ACTIONS:
            uid = int((metadata or {}).get("user_id", 0) or 0)
            if uid:
                queue_user(db, uid, apps)
            queue_group(db, tid)
        else:
            queue_group(db, tid)
    except (TypeError, ValueError):
        return
    except Exception:  # noqa: BLE001 - provisioning must never break the change that triggered it
        logger.exception("provisioning.hook_failed", action=name)


# ---- reconciliation --------------------------------------------------------------------------------------------

def _link(db: Session, app_id: int, *, user_id: Optional[int] = None, group_id: Optional[int] = None) -> Optional[ProvisioningLink]:
    q = db.query(ProvisioningLink).filter(ProvisioningLink.app_id == app_id)
    q = q.filter(ProvisioningLink.user_id == user_id) if user_id is not None else q.filter(ProvisioningLink.group_id == group_id)
    return q.first()


def _stamp(link: ProvisioningLink, h: Optional[str], state: str = "synced") -> None:
    link.state, link.last_error, link.last_synced_at = state, None, now()
    if h is not None:
        link.payload_hash = h


def sync_user(db: Session, app: ProvisioningApp, ad: adapters.Adapter, user_id: int) -> str:
    opts = options_of(app)
    user = db.get(User, user_id)
    link = _link(db, app.id, user_id=user_id)
    if user is None:
        return "skipped"  # the orphan sweep deprovisions it
    desired = user.status == "active" and is_entitled(db, app, user_id)
    if desired:
        doc = mapping.user_resource(user, app, active=True)
        h = mapping.payload_hash(doc)
        if link is None:
            if not opts["push_new_users"]:
                return "skipped"
            rid, result = ad.find_user(doc), "linked"
            if rid is None:
                try:
                    rid, result = ad.create_user(doc), "created"
                except adapters.Conflict:
                    rid = ad.find_user(doc)
                    if rid is None:
                        raise
            link = ProvisioningLink(app_id=app.id, resource_type="user", user_id=user.id, label=user.email, remote_id=rid, state="synced")
            db.add(link)
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                raise adapters.Retryable("another worker linked this user at the same time")
            if result == "linked" and opts["push_updates"]:
                ad.update_user(rid, doc)
            _stamp(link, h)
            return result
        if link.state == "deprovisioned":
            ad.set_active(link.remote_id, doc, True)
            if opts["push_updates"]:
                ad.update_user(link.remote_id, doc)
            _stamp(link, h)
            return "reactivated"
        if link.payload_hash != h and opts["push_updates"]:
            ad.update_user(link.remote_id, doc)
            _stamp(link, h)
            return "updated"
        if link.state == "error":
            _stamp(link, None)
        return "unchanged"
    if link is None or link.state == "deprovisioned":
        return "unchanged"
    mode = opts["deactivate"]
    if mode == "delete":
        ad.delete_user(link.remote_id)
        db.delete(link)
        return "deleted"
    if mode == "patch":
        ad.set_active(link.remote_id, mapping.user_resource(user, app, active=False), False)
        link.label = user.email
        _stamp(link, None, "deprovisioned")
        return "deactivated"
    _stamp(link, None, "deprovisioned")  # "none": we stop managing it without touching the app
    return "skipped"


def sync_group(db: Session, app: ProvisioningApp, ad: adapters.Adapter, group_id: int) -> str:
    link = _link(db, app.id, group_id=group_id)
    group = db.get(Group, group_id)
    wanted = group is not None and group_id in set(assigned_group_ids(db, app.id)) and options_of(app)["push_groups"] and ad.supports_groups
    if not wanted:
        if link is None:
            return "unchanged"
        ad.delete_group(link.remote_id)
        db.delete(link)
        return "deleted"
    rids = [rid for (rid,) in db.query(ProvisioningLink.remote_id).filter(
        ProvisioningLink.app_id == app.id, ProvisioningLink.resource_type == "user", ProvisioningLink.state == "synced",
        ProvisioningLink.user_id.in_(group_members(db, group_id) or [0])).all()]
    doc = mapping.group_resource(group, sorted(rids))
    h = mapping.payload_hash(doc)
    if link is None:
        rid = ad.find_group(doc)
        result = "linked"
        if rid is None:
            rid, result = ad.create_group(doc), "created"
        else:
            ad.update_group(rid, doc)
        link = ProvisioningLink(app_id=app.id, resource_type="group", group_id=group.id, label=group.name, remote_id=rid)
        db.add(link)
        _stamp(link, h)
        return result
    if link.payload_hash != h:
        ad.update_group(link.remote_id, doc)
        link.label = group.name
        _stamp(link, h)
        return "updated"
    return "unchanged"


def sweep_orphans(db: Session) -> int:
    """Links whose user/group row is gone: deprovision remotely per the app's policy, then forget them."""
    n = 0
    for link in db.query(ProvisioningLink).filter(ProvisioningLink.user_id.is_(None), ProvisioningLink.group_id.is_(None)).all():
        n += queue(db, link.app_id, link.resource_type, op="delete_remote", link_id=link.id)
    return n


def delete_remote(db: Session, app: ProvisioningApp, ad: adapters.Adapter, link_id: Optional[int]) -> str:
    link = db.get(ProvisioningLink, link_id) if link_id else None
    if link is None or link.app_id != app.id:
        return "unchanged"
    if link.resource_type == "group":
        ad.delete_group(link.remote_id)
    elif link.state != "deprovisioned":
        mode = options_of(app)["deactivate"]
        if mode == "delete":
            ad.delete_user(link.remote_id)
        elif mode == "patch":
            ad.set_active(link.remote_id, {"userName": link.label, "active": False}, False)
    db.delete(link)
    return "deleted"
