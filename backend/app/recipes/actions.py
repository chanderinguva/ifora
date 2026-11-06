"""Step executors. Each one validates its own target, so a recipe can do exactly what its step type allows and
nothing else (ADR 008 T3): no admin flags, no system groups, no administrator accounts, no user-editable attributes.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Tuple

import structlog
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from backend.app.audit.model import AuditAction, AuditEvent
from backend.app.auth.sessions_util import revoke_user_sessions
from backend.app.groups import rules as group_rules
from backend.app.groups.model import Group, user_group_association
from backend.app.profiles import catalog as profile_catalog
from backend.app.recipes import crypto, events
from backend.app.recipes import templates as tpl
from backend.app.recipes.http_client import (
    EgressBlocked, HttpFailure, ResponseTooLarge, safe_request, validate_url, EgressPolicy,
)
from backend.app.recipes.models import RecipeConnection
from backend.app.recipes.redact import redact, redact_text, scrub
from backend.app.users.model import User

logger = structlog.get_logger(__name__)

# Test seam: tests put an EgressPolicy / resolver / transport here. Production leaves it empty.
http_overrides: Dict[str, Any] = {}


class StepError(Exception):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.message, self.retryable = message, retryable


@dataclass
class RunCtx:
    db: Session
    recipe_id: int
    job_id: int
    step_id: str
    data: dict  # template context: trigger / steps / recipe / job
    dry: bool
    taint: Callable[[str], None]
    secrets: list = field(default_factory=list)

    def render(self, value: Any, tainted_ok: bool = False) -> Any:
        try:
            return tpl.render_value(value, self.data, None if tainted_ok else self.taint)
        except tpl.TemplateError as e:
            raise StepError(str(e))


def audit_as_recipe(rc: RunCtx, action: AuditAction, target_id, target_type: str, meta: dict) -> None:
    meta = {**meta, "via_recipe": rc.recipe_id, "job_id": rc.job_id, "step": rc.step_id}
    rc.db.add(
        AuditEvent(
            action=action, actor_id=f"recipe:{rc.recipe_id}", actor_type="recipe",
            target_id=str(target_id), target_type=target_type, metadata=meta,
        )
    )
    events.emit_from_audit(rc.db, action, None, target_id, target_type, meta)


def _user(rc: RunCtx, cfg: dict) -> User:
    raw = rc.render(cfg["user"])
    if isinstance(raw, bool) or not (isinstance(raw, int) or (isinstance(raw, str) and raw.strip().isdigit())):
        raise StepError("the user datapill did not resolve to a user id")
    user = rc.db.get(User, int(raw))
    if user is None:
        raise StepError("user not found")
    return user


def _group(rc: RunCtx, cfg: dict) -> Group:
    g = rc.db.get(Group, cfg["group_id"])
    if g is None:
        raise StepError("group not found")
    if g.is_system_group:
        raise StepError("recipes cannot change system groups")
    return g


def _add_to_group(rc: RunCtx, cfg: dict):
    user, group = _user(rc, cfg), _group(rc, cfg)
    inp = {"user_id": user.id, "group_id": group.id}
    exists = rc.db.execute(
        select(user_group_association.c.user_id).where(
            user_group_association.c.user_id == user.id, user_group_association.c.group_id == group.id
        )
    ).first()
    out = {"user_id": user.id, "group_id": group.id, "changed": exists is None}
    if exists is None and not rc.dry:
        rc.db.execute(insert(user_group_association).values(
            user_id=user.id, group_id=group.id, added_by_user_id=None, rule_id=None, added_at=datetime.now(timezone.utc)
        ))
        group_rules._recount(rc.db, group.id)
        audit_as_recipe(rc, AuditAction.GROUP_MEMBER_ADDED, group.id, "group", {"user_id": user.id})
    return inp, out


def _remove_from_group(rc: RunCtx, cfg: dict):
    user, group = _user(rc, cfg), _group(rc, cfg)
    inp = {"user_id": user.id, "group_id": group.id}
    row = rc.db.execute(
        select(user_group_association.c.rule_id).where(
            user_group_association.c.user_id == user.id, user_group_association.c.group_id == group.id
        )
    ).first()
    if row is not None and row[0] is not None:
        raise StepError("this membership is managed by a group rule; change the rule instead")
    out = {"user_id": user.id, "group_id": group.id, "changed": row is not None}
    if row is not None and not rc.dry:
        rc.db.execute(delete(user_group_association).where(
            user_group_association.c.user_id == user.id, user_group_association.c.group_id == group.id
        ))
        group_rules._recount(rc.db, group.id)
        audit_as_recipe(rc, AuditAction.GROUP_MEMBER_REMOVED, group.id, "group", {"user_id": user.id})
    return inp, out


def _set_attribute(rc: RunCtx, cfg: dict):
    user = _user(rc, cfg)
    defs = profile_catalog.by_key(rc.db)
    attr = defs.get(cfg["attribute"])
    if attr is None or attr.user_editable:
        raise StepError(f"'{cfg['attribute']}' is not an administrator-managed profile attribute")
    raw = rc.render(cfg["value"])
    if isinstance(raw, (dict, list)):
        raise StepError("an attribute value must be text, a number or true/false")
    try:
        value = profile_catalog.coerce_value(attr, raw)
    except profile_catalog.AttributeError_ as e:
        raise StepError(str(e))
    inp = {"user_id": user.id, "attribute": attr.key, "value": value}
    old = dict(user.get_profile_attributes())
    new = {k: v for k, v in old.items() if k != attr.key}
    if value is not None:
        new[attr.key] = value
    changed = new != old
    if changed and not rc.dry:
        user.set_profile_attributes(new)
        rc.db.flush()
        events.emit_attribute_changes(rc.db, user, old, new)
        group_rules.evaluate_user(rc.db, user)
        audit_as_recipe(rc, AuditAction.USER_UPDATED, user.id, "user", {"changed": {"profile_attributes": [attr.key]}})
    return inp, {"user_id": user.id, "attribute": attr.key, "value": value, "changed": changed}


def _set_status(rc: RunCtx, cfg: dict, status: str):
    user = _user(rc, cfg)
    if user.is_admin or user.is_super_admin:
        raise StepError("recipes cannot change administrator accounts")
    changed = user.status != status
    if changed and not rc.dry:
        user.status = status
        rc.db.flush()
        if status == "inactive":
            revoke_user_sessions(rc.db, user.id)
        group_rules.evaluate_user(rc.db, user)
        audit_as_recipe(rc, AuditAction.USER_DEACTIVATED if status == "inactive" else AuditAction.USER_ACTIVATED,
                        user.id, "user", {"changed": {"status": status}})
    return {"user_id": user.id}, {"user_id": user.id, "changed": changed}


def _activate(rc, cfg):
    return _set_status(rc, cfg, "active")


def _deactivate(rc, cfg):
    return _set_status(rc, cfg, "inactive")


def _log(rc: RunCtx, cfg: dict):
    msg = str(rc.render(cfg["message"], tainted_ok=True))[:1000]
    logger.info("recipe.log", recipe_id=rc.recipe_id, job_id=rc.job_id, step=rc.step_id)  # message stays in job history only
    return {"message": msg}, {"message": msg}


_SENSITIVE_QS = re.compile(r"([?&][^=&]*(?:token|secret|key|passw|signature|auth)[^=&]*=)[^&]*", re.I)


def _http(rc: RunCtx, cfg: dict):
    method = cfg["method"]
    url = str(rc.render(cfg["url"], tainted_ok=True))
    headers = {k: str(rc.render(v, tainted_ok=True)) for k, v in cfg["headers"].items()}
    body = rc.render(cfg["body"], tainted_ok=True) if cfg.get("body") is not None else None
    body_bytes = None if body is None else (body if isinstance(body, str) else json.dumps(body)).encode()
    policy = http_overrides.get("policy") or EgressPolicy.from_settings()
    conn_name = None
    secret_value = None
    try:
        if cfg.get("connection_id") is not None:
            conn = rc.db.get(RecipeConnection, cfg["connection_id"])
            if conn is None:
                raise StepError("connection not found")
            conn_name = conn.name
            _, host, _, _ = validate_url(url, policy)
            if host != conn.allowed_host.lower():
                raise StepError("this connection may only be used for " + conn.allowed_host)
            if not rc.dry:
                try:
                    secret_value = crypto.decrypt(conn.secret_enc)
                except crypto.RecipeKeyError as e:
                    raise StepError(str(e))
                rc.secrets.append(secret_value)
                if conn.kind == "bearer":
                    headers["Authorization"] = f"Bearer {secret_value}"
                else:
                    headers[conn.header_name or "X-Api-Key"] = secret_value
        else:
            validate_url(url, policy)
    except EgressBlocked as e:
        raise StepError(f"blocked: {e}")
    if body_bytes is not None and not any(k.lower() == "content-type" for k in headers):
        headers["Content-Type"] = "application/json"
    headers["Idempotency-Key"] = f"{rc.job_id}-{rc.step_id}"
    inp = redact({
        "method": method, "url": _SENSITIVE_QS.sub(r"\1[REDACTED]", url),
        "headers": {k: v for k, v in headers.items() if k != "Idempotency-Key"},
        "body": (body_bytes.decode(errors="replace")[:2000] if body_bytes is not None else None),
        "connection": conn_name,
    })
    if secret_value:
        inp = scrub(inp, [secret_value])
    if rc.dry:
        return inp, {"dry_run": True, "status_code": None, "ok": None, "body": "", "json": None}
    try:
        res = safe_request(
            method, url, headers, body_bytes, policy=policy, resolver=http_overrides.get("resolver"),
            transport=http_overrides.get("transport"),
        )
    except EgressBlocked as e:
        raise StepError(f"blocked: {e}")
    except ResponseTooLarge:
        raise StepError("the response was too large")
    except HttpFailure as e:
        raise StepError(str(e), retryable=True)
    text = res.body.decode("utf-8", errors="replace")
    parsed = None
    if "json" in res.content_type.lower() and len(res.body) <= 32768:
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
    out = {
        "status_code": res.status, "ok": 200 <= res.status < 300, "body": redact_text(text[:4000]), "json": parsed,
    }
    out = redact(scrub(out, rc.secrets))
    if res.status == 429 or res.status >= 500:
        raise StepError(f"remote server answered {res.status}", retryable=True)
    if 400 <= res.status < 500:
        raise StepError(f"remote server answered {res.status}")
    return inp, out


EXECUTORS: Dict[str, Callable[[RunCtx, dict], Tuple[dict, dict]]] = {
    "add_to_group": _add_to_group, "remove_from_group": _remove_from_group, "set_attribute": _set_attribute,
    "activate_user": _activate, "deactivate_user": _deactivate, "http_request": _http, "log": _log,
}
