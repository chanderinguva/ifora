"""Recipe export/import and the starter-template catalog (ADR 008 R-M6).

A file never carries secrets, webhook secrets, ids of other tenants' objects or job history. Groups and connections are
stored by NAME next to the ids they had, and re-resolved by name on import, so a recipe moves between environments.
Imports always land as an unpublished, disabled draft and go through the same validation as an edited draft.
"""

import copy
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.app.groups.model import Group
from backend.app.recipes.models import Recipe, RecipeConnection

FORMAT = "identityforge.recipe"
FORMAT_VERSION = 1
MAX_IMPORT_BYTES = 200_000


class ImportError_(ValueError):
    """Safe to show to the administrator."""


def _walk(defn: dict):
    """Yield every config dict that may hold a group_id / connection_id (trigger, steps, branches, handler)."""
    yield defn.get("trigger", {}).get("config", {})

    def steps(items):
        for s in items or []:
            yield s.get("config", {})
            yield from steps(s.get("then"))
            yield from steps(s.get("else"))

    yield from steps(defn.get("steps"))
    yield from steps(defn.get("on_error"))


def export_document(db: Session, r: Recipe) -> dict:
    d = copy.deepcopy(r.draft)
    groups: Dict[str, str] = {}
    conns: Dict[str, str] = {}
    for cfg in _walk(d):
        gid, cid = cfg.get("group_id"), cfg.get("connection_id")
        if isinstance(gid, int) and gid not in map(int, groups):
            g = db.get(Group, gid)
            if g:
                groups[str(gid)] = g.name
        if isinstance(cid, int) and cid not in map(int, conns):
            c = db.get(RecipeConnection, cid)
            if c:
                conns[str(cid)] = c.name
    return {
        "format": FORMAT, "format_version": FORMAT_VERSION, "name": r.name, "description": r.description,
        "references": {"groups": groups, "connections": conns}, "definition": d,
    }


def resolve_import(db: Session, doc: Any) -> Tuple[str, Optional[str], dict, List[str]]:
    """Validate the envelope and re-map group/connection references by name. Returns (name, description, definition, warnings)."""
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise ImportError_("this is not an Ifora recipe file")
    if doc.get("format_version") != FORMAT_VERSION:
        raise ImportError_(f"unsupported file version {doc.get('format_version')!r}")
    d = doc.get("definition")
    if not isinstance(d, dict) or not isinstance(d.get("steps"), list):
        raise ImportError_("the file has no recipe definition")
    refs = doc.get("references") or {}
    if not isinstance(refs, dict):
        raise ImportError_("invalid references")
    gnames, cnames = refs.get("groups") or {}, refs.get("connections") or {}
    if not isinstance(gnames, dict) or not isinstance(cnames, dict):
        raise ImportError_("invalid references")
    d = copy.deepcopy(d)
    problems: List[str] = []
    gmap: Dict[int, int] = {}
    cmap: Dict[int, int] = {}
    for key, name in gnames.items():
        g = db.query(Group).filter(Group.name == str(name)).first()
        if g is None:
            problems.append(f"group '{name}' does not exist here")
        else:
            gmap[int(key)] = g.id
    for key, name in cnames.items():
        c = db.query(RecipeConnection).filter(RecipeConnection.name == str(name)).first()
        if c is None:
            problems.append(f"connection '{name}' does not exist here (create it under Connections first)")
        else:
            cmap[int(key)] = c.id
    for cfg in _walk(d):
        gid, cid = cfg.get("group_id"), cfg.get("connection_id")
        if isinstance(gid, int) and not isinstance(gid, bool):
            if gid in gmap:
                cfg["group_id"] = gmap[gid]
            else:
                cfg["group_id"] = None
        if isinstance(cid, int) and not isinstance(cid, bool):
            if cid in cmap:
                cfg["connection_id"] = cmap[cid]
            else:
                cfg["connection_id"] = None
    if problems:
        raise ImportError_("cannot import: " + "; ".join(sorted(set(problems))))
    name = str(doc.get("name") or "Imported recipe").strip()[:100] or "Imported recipe"
    desc = doc.get("description")
    return name, (str(desc)[:500] if desc else None), d, []


# ---- templates -------------------------------------------------------------------------------------------------

def _log(i, msg):
    return {"id": i, "type": "log", "config": {"message": msg}}


TEMPLATES: List[dict] = [
    {
        "id": "welcome-group", "name": "Add new users to a group",
        "description": "When an account is created, put the person in a group (for example an onboarding or all-staff group).",
        "params": [{"key": "group", "label": "Group", "type": "group"}],
        "build": lambda p: {
            "trigger": {"type": "user.created", "config": {}, "filter": []},
            "steps": [{"id": "s1", "type": "add_to_group", "config": {"group_id": p["group"], "user": "{{trigger.user.id}}"}}],
        },
    },
    {
        "id": "offboarding", "name": "Offboarding: remove from a group when deactivated",
        "description": "When an account is deactivated, remove it from a group and leave a note in the job log.",
        "params": [{"key": "group", "label": "Group to remove them from", "type": "group"}],
        "build": lambda p: {
            "trigger": {"type": "user.deactivated", "config": {}, "filter": []},
            "steps": [
                {"id": "s1", "type": "remove_from_group", "config": {"group_id": p["group"], "user": "{{trigger.user.id}}"}},
                _log("s2", "Offboarded {{trigger.user.email}}"),
            ],
        },
    },
    {
        "id": "attribute-to-group", "name": "Move people to a group when an attribute changes",
        "description": "When an administrator-managed attribute is set to a value, add the person to a group.",
        "params": [
            {"key": "attribute", "label": "Attribute", "type": "attribute"},
            {"key": "value", "label": "Becomes this value", "type": "text"},
            {"key": "group", "label": "Add to group", "type": "group"},
        ],
        "build": lambda p: {
            "trigger": {"type": "user.attribute_changed", "config": {"attribute": p["attribute"], "to_value": p["value"]}, "filter": []},
            "steps": [{"id": "s1", "type": "add_to_group", "config": {"group_id": p["group"], "user": "{{trigger.user.id}}"}}],
        },
    },
    {
        "id": "approved-group-access", "name": "Group access that needs an approval",
        "description": "When an account is created, ask an administrator before adding it to a group. Denied or unanswered requests do nothing.",
        "params": [{"key": "group", "label": "Group", "type": "group"}],
        "build": lambda p: {
            "trigger": {"type": "user.created", "config": {}, "filter": []},
            "steps": [{
                "id": "s1", "type": "approval", "config": {"message": "Add {{trigger.user.email}} to the group?", "timeout_hours": 48},
                "then": [{"id": "s2", "type": "add_to_group", "config": {"group_id": p["group"], "user": "{{trigger.user.id}}"}}],
                "else": [_log("s3", "Access not granted to {{trigger.user.email}}: {{steps.s1.output.decision}}")],
            }],
        },
    },
    {
        "id": "failed-login-slack", "name": "Slack alert after repeated failed sign-ins",
        "description": "Post to Slack when an account has several consecutive failed sign-ins.",
        "params": [{"key": "connection", "label": "Slack connection", "type": "slack_connection"},
                   {"key": "min_failures", "label": "After this many failures", "type": "number"}],
        "build": lambda p: {
            "trigger": {"type": "login.failed", "config": {"min_failures": int(p["min_failures"])}, "filter": []},
            "steps": [{"id": "s1", "type": "connector_action", "config": {"connector": "slack", "action": "post_message",
                       "connection_id": p["connection"], "inputs": {"channel": p["channel"],
                       "text": "{{trigger.user.email}} has {{trigger.login.consecutive_failures}} failed sign-ins in a row"}}}]
                       if p.get("slack_bot") else [{"id": "s1", "type": "send_slack", "config": {"connection_id": p["connection"],
                       "message": "{{trigger.user.email}} has {{trigger.login.consecutive_failures}} failed sign-ins in a row"}}],
        },
    },
]
BY_ID = {t["id"]: t for t in TEMPLATES}


def public_catalog() -> List[dict]:
    return [{k: v for k, v in t.items() if k != "build"} for t in TEMPLATES]
