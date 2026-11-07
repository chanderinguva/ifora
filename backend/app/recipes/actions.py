"""Step executors. Each one validates its own target, so a recipe can do exactly what its step type allows and
nothing else (ADR 008 T3): no admin flags, no system groups, no administrator accounts, no user-editable attributes.
"""

import json
import re
import smtplib
import time
from email.message import EmailMessage
from urllib.parse import unquote, urlencode
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
from backend.app.config import settings
from backend.app.recipes.redact import redact, redact_text, scrub
from backend.app.users import lifecycle
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
        lifecycle.set_status(rc.db, user, status, None, None, audit=False)
        audit_as_recipe(rc, AuditAction.USER_DEACTIVATED if status == "deprovisioned" else AuditAction.USER_ACTIVATED,
                        user.id, "user", {"changed": {"status": status}})
    return {"user_id": user.id}, {"user_id": user.id, "changed": changed}


def _activate(rc, cfg):
    return _set_status(rc, cfg, "active")


def _deactivate(rc, cfg):
    return _set_status(rc, cfg, "deprovisioned")


def _log(rc: RunCtx, cfg: dict):
    msg = str(rc.render(cfg["message"], tainted_ok=True))[:1000]
    logger.info("recipe.log", recipe_id=rc.recipe_id, job_id=rc.job_id, step=rc.step_id)  # message stays in job history only
    return {"message": msg}, {"message": msg}


_SENSITIVE_QS = re.compile(r"([?&][^=&]*(?:token|secret|key|passw|signature|auth)[^=&]*=)[^&]*", re.I)


_ENCODED_TRICKS = re.compile(r"%(2e|2f|5c)", re.I)


def path_allowed(path_and_query: str, prefixes) -> bool:
    """Is the URL path inside one of the connection's allow-listed prefixes? No list = any path on the host.
    Traversal ("..", encoded dots or slashes, backslashes) is refused outright so a prefix cannot be escaped."""
    if not prefixes:
        return True
    path = path_and_query.split("?", 1)[0]
    if _ENCODED_TRICKS.search(path) or "\\" in path or "//" in path:
        return False
    if any(seg in ("..", ".") for seg in unquote(path).split("/")):
        return False
    for p in prefixes:
        if path == p or path.startswith(p if p.endswith("/") else p + "/"):
            return True
    return False


_token_cache: Dict[Tuple[int, str], Tuple[str, float]] = {}  # per process; keyed by connection id + last edit, so rotating the secret drops it


def _oauth_token(rc: RunCtx, conn: RecipeConnection, client_secret: str, policy) -> str:
    key = (conn.id, conn.updated_at.isoformat())
    hit = _token_cache.get(key)
    if hit and hit[1] > time.monotonic():
        return hit[0]
    try:
        _, host, _, _ = validate_url(conn.token_url or "", policy)
        if host != conn.allowed_host.lower():
            raise StepError("the token URL must be on the connection's host")
        form = {"grant_type": "client_credentials", "client_id": conn.client_id or "", "client_secret": client_secret}
        if conn.scope:
            form["scope"] = conn.scope
        res = safe_request(
            "POST", conn.token_url, {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            urlencode(form).encode(), policy=policy, resolver=http_overrides.get("resolver"), transport=http_overrides.get("transport"),
        )
    except EgressBlocked as e:
        raise StepError(f"blocked: {e}")
    except ResponseTooLarge:
        raise StepError("the token response was too large")
    except HttpFailure as e:
        raise StepError(str(e), retryable=True)
    if res.status >= 500 or res.status == 429:
        raise StepError(f"token endpoint answered {res.status}", retryable=True)
    try:
        data = json.loads(res.body.decode("utf-8", errors="replace"))
        token = data["access_token"]
        if res.status != 200 or not isinstance(token, str) or not token or "\r" in token or "\n" in token:
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise StepError(f"the token endpoint refused the credentials (status {res.status})")
    ttl = data.get("expires_in")
    ttl = min(max(int(ttl), 30), 3600) if isinstance(ttl, (int, float)) and not isinstance(ttl, bool) else 300
    _token_cache[key] = (token, time.monotonic() + ttl - 20)
    return token


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
            if conn.kind == "slack_webhook":
                raise StepError("Slack connections can only be used by the Slack step")
            _, host, _, path = validate_url(url, policy)
            if host != conn.allowed_host.lower():
                raise StepError("this connection may only be used for " + conn.allowed_host)
            if not path_allowed(path, conn.allowed_paths):
                raise StepError("this connection may not be used for that path")
            if not rc.dry:
                try:
                    secret_value = crypto.decrypt(conn.secret_enc)
                except crypto.RecipeKeyError as e:
                    raise StepError(str(e))
                rc.secrets.append(secret_value)
                if conn.kind == "bearer":
                    headers["Authorization"] = f"Bearer {secret_value}"
                elif conn.kind == "oauth2_client_credentials":
                    token = _oauth_token(rc, conn, secret_value, policy)
                    rc.secrets.append(token)
                    headers["Authorization"] = f"Bearer {token}"
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


def _slack(rc: RunCtx, cfg: dict):
    conn = rc.db.get(RecipeConnection, cfg["connection_id"])
    if conn is None or conn.kind != "slack_webhook":
        raise StepError("choose a Slack webhook connection")
    raw = str(rc.render(cfg["message"], tainted_ok=True))[:3000]
    # Slack treats & < > as markup: escaping them stops user-controlled text from @-mentioning channels or smuggling links
    text = raw.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    inp = {"connection": conn.name, "message": text}
    if rc.dry:
        return inp, {"ok": None, "dry_run": True}
    try:
        url = crypto.decrypt(conn.secret_enc)
    except crypto.RecipeKeyError as e:
        raise StepError(str(e))
    rc.secrets.append(url)
    policy = http_overrides.get("policy") or EgressPolicy.from_settings()
    try:
        validate_url(url, policy)
        res = safe_request("POST", url, {"Content-Type": "application/json"}, json.dumps({"text": text}).encode(), policy=policy,
                           resolver=http_overrides.get("resolver"), transport=http_overrides.get("transport"))
    except EgressBlocked as e:
        raise StepError(f"blocked: {e}")
    except (HttpFailure, ResponseTooLarge) as e:
        raise StepError(str(e) or "Slack request failed", retryable=True)
    if res.status == 429 or res.status >= 500:
        raise StepError(f"Slack answered {res.status}", retryable=True)
    if res.status != 200:
        raise StepError(f"Slack answered {res.status}")
    return inp, {"ok": True}


_ADDR = re.compile(r"^[A-Za-z0-9._%+'-]{1,64}@([A-Za-z0-9-]{1,63}\.)+[A-Za-z]{2,24}$")
mail_overrides: Dict[str, Any] = {}  # test seam: {"send": callable(EmailMessage)}


def _smtp_send(msg: EmailMessage) -> None:
    if "send" in mail_overrides:
        return mail_overrides["send"](msg)
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=settings.RECIPES_HTTP_TIMEOUT_SECONDS) as smtp:
        if settings.SMTP_STARTTLS:
            smtp.starttls()
        if settings.SMTP_USERNAME:
            smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        smtp.send_message(msg)


def _email(rc: RunCtx, cfg: dict):
    to = str(rc.render(cfg["to"], tainted_ok=True)).strip().lower()
    subject = str(rc.render(cfg["subject"], tainted_ok=True)).strip()
    body = str(rc.render(cfg["body"], tainted_ok=True))[:5000]
    if not _ADDR.match(to):
        raise StepError("the recipient is not a single valid email address")
    if any(c in subject for c in "\r\n") or not subject:
        raise StepError("the subject must be one non-empty line")
    domains = {d.strip().lower() for d in settings.RECIPES_EMAIL_ALLOWED_DOMAINS.split(",") if d.strip()}
    known = rc.db.query(User.id).filter(User.email == to, User.status == "active").first() is not None
    if not known and to.rsplit("@", 1)[1] not in domains:
        raise StepError("the recipient is neither an active user nor in an allowed email domain")
    inp = {"to": to, "subject": subject[:200], "body": body[:2000]}
    if rc.dry:
        return inp, {"to": to, "sent": False, "dry_run": True}
    if not (settings.SMTP_HOST and settings.SMTP_FROM) and "send" not in mail_overrides:
        raise StepError("email is not configured on this server")
    from backend.app.recipes.models import RecipeJobStep
    done = rc.db.query(RecipeJobStep).filter(RecipeJobStep.job_id == rc.job_id, RecipeJobStep.type == "send_email",
                                             RecipeJobStep.status == "succeeded").count()
    if done >= settings.RECIPES_MAX_EMAILS_PER_JOB:
        raise StepError(f"a job may send at most {settings.RECIPES_MAX_EMAILS_PER_JOB} emails")
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = settings.SMTP_FROM or "noreply@localhost", to, subject
    msg["X-IdentityForge-Job"] = f"{rc.job_id}-{rc.step_id}"
    msg.set_content(body)
    try:
        _smtp_send(msg)
    except smtplib.SMTPRecipientsRefused:
        raise StepError("the mail server refused the recipient")
    except (smtplib.SMTPException, OSError):
        raise StepError("sending the email failed", retryable=True)
    return inp, {"to": to, "sent": True}


EXECUTORS: Dict[str, Callable[[RunCtx, dict], Tuple[dict, dict]]] = {
    "add_to_group": _add_to_group, "remove_from_group": _remove_from_group, "set_attribute": _set_attribute,
    "activate_user": _activate, "deactivate_user": _deactivate, "http_request": _http, "log": _log,
    "send_slack": _slack, "send_email": _email,
}
