"""Recipe definitions: validation, the datapill catalog, and compilation to a flat program (ADR 008 D2).

Definition JSON::

    {"trigger": {"type": "user.created", "config": {}, "filter": [{"left": "...", "operator": "...", "value": "..."}]},
     "on_error": [ ...steps run when a step fails for good (optional; see ADR 008 R-M2)... ],
     "steps": [{"id": "s1", "type": "add_to_group", "name": "...", "config": {...}, "on_error": "fail",
                "max_attempts": 3},
               {"id": "c1", "type": "condition", "config": {"match": "all", "conditions": [...]},
                "then": [...], "else": [...]}]}
"""

import re
from typing import Any, Callable, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from backend.app.groups.model import Group
from backend.app.profiles import catalog as profile_catalog
from backend.app.recipes import conditions as cond
from backend.app.recipes import lookup
from backend.app.recipes import templates as tpl
from backend.app.recipes.models import RecipeConnection

MAX_STEPS = 30
MAX_NESTING = 3
MAX_DEFINITION_BYTES = 65536
_ID = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

EVENT_TRIGGERS = (
    "user.created", "user.activated", "user.deactivated", "user.updated", "user.attribute_changed",
    "group.member_added", "group.member_removed", "login.failed",
    "user.deleted", "group.created", "group.deleted", "login.succeeded",
    "session.logout", "mfa.enabled", "mfa.disabled", "password.changed",
)
TRIGGER_TYPES = EVENT_TRIGGERS + ("schedule", "manual", "webhook")
ACTION_TYPES = (
    "add_to_group", "remove_from_group", "set_attribute", "activate_user", "deactivate_user", "http_request", "log",
    "send_slack", "send_email", "lookup_row", "lookup_write",
)
STEP_TYPES = ACTION_TYPES + ("condition", "stop", "for_each_member", "approval", "set_variable", "wait", "throttle")
BRANCHING = ("condition", "approval")  # then/else steps
MAX_LOOP_MEMBERS = 100
MAX_VARIABLES = 20
MAX_WAIT_MINUTES = 7 * 24 * 60
WAIT_UNIT_MINUTES = {"minutes": 1, "hours": 60, "days": 1440}
STATE_CHANGING = ("add_to_group", "remove_from_group", "set_attribute", "activate_user", "deactivate_user")


class DefinitionError(ValueError):
    """The definition is invalid; the message is safe to show to the admin."""


class _Cfg(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _TrigNone(_Cfg):
    pass


class _TrigGroup(_Cfg):
    group_id: Optional[int] = None


class _TrigAttribute(_Cfg):
    attribute: str = Field(..., min_length=1, max_length=50)
    from_value: Optional[str] = Field(None, max_length=500)  # only when the old value equals this ("" = it was unset)
    to_value: Optional[str] = Field(None, max_length=500)    # only when the new value equals this ("" = it became unset)


class _TrigLogin(_Cfg):
    min_failures: int = Field(1, ge=1, le=100)


class _TrigSchedule(_Cfg):
    interval_minutes: int = Field(..., ge=5, le=1440)


TRIGGER_CFG = {
    **{t: _TrigNone for t in ("user.created", "user.activated", "user.deactivated", "user.updated", "manual", "webhook",
                              "user.deleted", "group.created", "group.deleted", "login.succeeded",
                              "session.logout", "mfa.enabled", "mfa.disabled", "password.changed")},
    "group.member_added": _TrigGroup, "group.member_removed": _TrigGroup,
    "user.attribute_changed": _TrigAttribute, "login.failed": _TrigLogin, "schedule": _TrigSchedule,
}

_USER_DEFAULT = "{{trigger.user.id}}"


class _AddRemove(_Cfg):
    group_id: int
    user: str = Field(_USER_DEFAULT, max_length=200)


class _SetAttr(_Cfg):
    user: str = Field(_USER_DEFAULT, max_length=200)
    attribute: str = Field(..., min_length=1, max_length=50)
    value: str = Field("", max_length=500)


class _UserOnly(_Cfg):
    user: str = Field(_USER_DEFAULT, max_length=200)


class _Http(_Cfg):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "POST"
    url: str = Field(..., min_length=1, max_length=2000)
    headers: Dict[str, str] = Field(default_factory=dict)
    body: Optional[str] = Field(None, max_length=10000)
    connection_id: Optional[int] = None


class _Slack(_Cfg):
    connection_id: int
    message: str = Field(..., min_length=1, max_length=3000)


class _Email(_Cfg):
    to: str = Field(..., min_length=3, max_length=320)
    subject: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1, max_length=5000)


class _Log(_Cfg):
    message: str = Field(..., min_length=1, max_length=1000)


class _Condition(_Cfg):
    match: Literal["all", "any"] = "all"
    conditions: List[Dict[str, Any]]


class _Loop(_Cfg):
    group_id: int
    limit: int = Field(50, ge=1, le=MAX_LOOP_MEMBERS)  # at most this many members (lowest ids first); the rest are skipped


class _Approval(_Cfg):
    message: str = Field(..., min_length=1, max_length=500)
    timeout_hours: int = Field(24, ge=1, le=168)  # no decision in time = "denied" branch


class _Stop(_Cfg):
    outcome: Literal["success", "failed"] = "success"
    message: str = Field("", max_length=500)


class _SetVar(_Cfg):
    name: str = Field(..., pattern=r"^[a-z][a-z0-9_]{0,31}$")
    value: str = Field("", max_length=1000)


class _Wait(_Cfg):
    amount: int = Field(..., ge=1, le=10080)
    unit: Literal["minutes", "hours", "days"] = "minutes"


class _Throttle(_Cfg):
    max_runs: int = Field(..., ge=1, le=1000)      # at most this many jobs may pass this step ...
    per_minutes: int = Field(..., ge=1, le=1440)   # ... in any window of this length
    when_full: Literal["wait", "stop"] = "wait"    # wait for a free slot, or drop (cancel) the job


_IDENT = r"^[a-z][a-z0-9_]{0,39}$"


class _LookupRow(_Cfg):
    table: str = Field(..., pattern=_IDENT)
    column: str = Field(..., pattern=_IDENT)
    value: str = Field(..., min_length=1, max_length=500)


class _LookupWrite(_Cfg):
    table: str = Field(..., pattern=_IDENT)
    action: Literal["add", "upsert", "delete"] = "upsert"
    values: Dict[str, str] = Field(default_factory=dict)   # column -> template (add, upsert)
    key: str = Field("", max_length=500)                   # template (delete)


STEP_CFG = {
    "lookup_row": _LookupRow, "lookup_write": _LookupWrite,
    "set_variable": _SetVar, "wait": _Wait, "throttle": _Throttle,
    "add_to_group": _AddRemove, "remove_from_group": _AddRemove, "set_attribute": _SetAttr,
    "activate_user": _UserOnly, "deactivate_user": _UserOnly, "http_request": _Http, "log": _Log,
    "send_slack": _Slack, "send_email": _Email,
    "condition": _Condition, "stop": _Stop, "for_each_member": _Loop, "approval": _Approval,
}

# datapill catalog ------------------------------------------------------------------------------
_COMMON = [
    ("trigger.event.id", "Event id"), ("trigger.event.type", "Event type"), ("trigger.event.occurred_at", "Occurred at"),
    ("trigger.actor.type", "Actor type"), ("trigger.actor.id", "Actor id"),
]
_USER = [
    ("trigger.user.id", "User id"), ("trigger.user.email", "User email"), ("trigger.user.username", "Username"),
    ("trigger.user.first_name", "First name"), ("trigger.user.last_name", "Last name"), ("trigger.user.status", "Account status"),
]
_GROUP = [("trigger.group.id", "Group id"), ("trigger.group.name", "Group name")]
TRIGGER_FIELDS = {
    **{t: _COMMON + _USER for t in ("user.created", "user.activated", "user.deactivated", "user.updated")},
    "user.attribute_changed": _COMMON + _USER + [
        ("trigger.attribute.key", "Attribute"), ("trigger.attribute.old", "Old value"), ("trigger.attribute.new", "New value")],
    "group.member_added": _COMMON + _USER + _GROUP,
    "group.member_removed": _COMMON + _USER + _GROUP,
    "group.created": _COMMON + _GROUP,
    "group.deleted": _COMMON + _GROUP,
    "user.deleted": _COMMON + [("trigger.user.id", "User id"), ("trigger.user.email", "User email")],
    "login.succeeded": _COMMON + _USER + [("trigger.login.method", "Sign-in method")],
    **{t: _COMMON + _USER for t in ("session.logout", "mfa.enabled", "mfa.disabled", "password.changed")},
    "login.failed": _COMMON + _USER + [("trigger.login.consecutive_failures", "Consecutive failures")],
    "schedule": _COMMON + [("trigger.schedule.scheduled_for", "Scheduled for")],
    "manual": _COMMON + _USER + [("trigger.manual.started_by", "Started by (admin id)")],
    "webhook": _COMMON,
}
_DYNAMIC_PREFIXES = {  # any suffix is allowed below these
    "trigger.user.attributes.": ("user.created", "user.activated", "user.deactivated", "user.updated",
                                 "user.attribute_changed", "group.member_added", "group.member_removed",
                                 "login.failed", "login.succeeded", "session.logout", "mfa.enabled", "mfa.disabled", "password.changed", "manual"),
    "trigger.payload.": ("manual", "webhook"),
}
STEP_OUTPUTS = {
    "add_to_group": ["user_id", "group_id", "changed"], "remove_from_group": ["user_id", "group_id", "changed"],
    "set_attribute": ["user_id", "attribute", "value", "changed"],
    "activate_user": ["user_id", "changed"], "deactivate_user": ["user_id", "changed"],
    "http_request": ["status_code", "ok", "body", "json"], "log": ["message"],
    "send_slack": ["ok"], "send_email": ["to", "sent"], "condition": ["result"], "stop": [],
    "for_each_member": ["total", "processed"], "approval": ["decision", "decided_by"],
    "lookup_row": ["found", "count", "row"], "lookup_write": ["action", "changed"],
    "set_variable": ["value"], "wait": ["waited_seconds"], "throttle": ["waited_seconds"],
}
_RECIPE_FIELDS = ["recipe.id", "recipe.name", "recipe.version", "job.id"]
_SAFE_USER_FIELDS = {"id", "email", "username", "status"}


def admin_managed_keys(db: Session) -> set:
    return {a.key for a in profile_catalog.catalog(db) if not a.user_editable}


def taint_checker(db: Session, tainted_step: Optional[Callable[[str], bool]] = None) -> Callable[[str], None]:
    """Refuse datapills a user can edit themselves (first/last name, self-editable attributes) and what a recipe reads
    from a recipe-writable lookup table (`tainted_step(id)` says which steps did). ADR 008 D2, ADR 021 section 2."""
    managed = admin_managed_keys(db)

    def check(path: str) -> None:
        segs = path.split(".")
        if segs[0] == "steps" and len(segs) > 1 and tainted_step is not None and tainted_step(segs[1]):
            raise tpl.TemplateError(
                f"'{path}' comes from a lookup table that recipes can write, so it cannot be used here; "
                "mark the table administrator-managed, or use it in log, http or email steps"
            )
        if segs[0] == "error":  # may carry text from a remote system or a user-controlled value
            raise tpl.TemplateError(f"'{path}' cannot be used to change accounts or make decisions; use it in log or http steps")
        if segs[:2] in (["trigger", "user"], ["loop", "user"]):
            ok = len(segs) == 3 and segs[2] in _SAFE_USER_FIELDS
            ok = ok or (len(segs) == 4 and segs[2] == "attributes" and segs[3] in managed)
            if not ok:
                raise tpl.TemplateError(
                    f"'{path}' can be edited by the user themselves, so it cannot be used here; "
                    "use email, username, status or an administrator-managed attribute"
                )

    return check


def trigger_field_paths(trigger_type: str, db: Session) -> List[Dict[str, str]]:
    out = [{"path": p, "label": l} for p, l in TRIGGER_FIELDS.get(trigger_type, [])]
    if any(trigger_type in ts for pre, ts in _DYNAMIC_PREFIXES.items() if pre == "trigger.user.attributes."):
        for a in profile_catalog.catalog(db):
            out.append({"path": f"trigger.user.attributes.{a.key}", "label": f"{a.display_name} (attribute)"})
    return out


ERROR_PILLS = ("error.message", "error.step_id")
LOOP_PILLS = ("loop.index", "loop.total", "loop.user.id", "loop.user.email", "loop.user.username", "loop.user.status")


def _pill_allowed(path: str, trigger_type: str, earlier_steps: Dict[str, str], db_keys: set, handler: bool = False, in_loop: bool = False) -> None:
    segs = path.split(".")
    if segs[0] == "loop":
        if not in_loop:
            raise tpl.TemplateError("loop datapills are only available inside a 'for each member' step")
        if path in LOOP_PILLS or (path.startswith("loop.user.attributes.") and len(segs) == 4 and segs[3] in db_keys):
            return
        raise tpl.TemplateError(f"unknown datapill '{path}'")
    if segs[0] == "vars":
        if f"$var:{segs[1]}" not in earlier_steps:
            raise tpl.TemplateError(f"variable '{segs[1]}' is not set by an earlier 'Set variable' step")
        return
    if segs[0] == "error":
        if handler and path in ERROR_PILLS:
            return
        raise tpl.TemplateError("error details are only available in the 'on error' steps" if not handler else f"unknown datapill '{path}'")
    if segs[0] == "trigger":
        if path in {p for p, _ in TRIGGER_FIELDS.get(trigger_type, [])}:
            return
        for pre, types in _DYNAMIC_PREFIXES.items():
            if path.startswith(pre) and trigger_type in types and len(segs) > len(pre.split(".")) - 1:
                return
        raise tpl.TemplateError(f"datapill '{path}' is not provided by the '{trigger_type}' trigger")
    if segs[0] == "steps":
        if len(segs) < 3 or segs[2] != "output" or segs[1] not in earlier_steps:
            raise tpl.TemplateError(f"datapill '{path}' must be steps.<earlier step id>.output.<field>")
        known = STEP_OUTPUTS.get(earlier_steps[segs[1]], []) + (["error"] if earlier_steps[segs[1]] in ACTION_TYPES else [])
        if len(segs) >= 4 and known and segs[3] not in known:
            raise tpl.TemplateError(f"step '{segs[1]}' has no output '{segs[3]}'")
        return
    if path not in _RECIPE_FIELDS:
        raise tpl.TemplateError(f"unknown datapill '{path}'")


# validation ---------------------------------------------------------------------------------------

def _pyd(model, data, where):
    try:
        return model.model_validate(data).model_dump()
    except ValidationError as e:
        err = e.errors()[0]
        loc = ".".join(str(x) for x in err["loc"])
        raise DefinitionError(f"{where}: {loc + ': ' if loc else ''}{err['msg']}")


def validate_definition(db: Session, definition: Any, *, for_publish: bool = False, actor=None) -> Dict[str, Any]:
    """Return the normalised definition or raise DefinitionError."""
    import json

    if not isinstance(definition, dict) or set(definition) - {"trigger", "steps", "on_error"}:
        raise DefinitionError("definition must contain 'trigger', 'steps' and optionally 'on_error' only")
    if len(json.dumps(definition)) > MAX_DEFINITION_BYTES:
        raise DefinitionError("definition is too large")
    trig = definition.get("trigger")
    if not isinstance(trig, dict) or set(trig) - {"type", "config", "filter"}:
        raise DefinitionError("trigger must have type, config and optional filter")
    ttype = trig.get("type")
    if ttype not in TRIGGER_TYPES:
        raise DefinitionError(f"unknown trigger '{ttype}'")
    tcfg = _pyd(TRIGGER_CFG[ttype], trig.get("config") or {}, "trigger")
    managed = admin_managed_keys(db)
    seen: Dict[str, str] = {}
    taint = taint_checker(db, lambda sid: ("$taint:" + sid) in seen)
    if ttype == "user.attribute_changed" and tcfg["attribute"] not in managed:
        raise DefinitionError("trigger: only administrator-managed attributes can trigger a recipe")
    if ttype in ("group.member_added", "group.member_removed") and tcfg.get("group_id") is not None:
        if db.get(Group, tcfg["group_id"]) is None:
            raise DefinitionError("trigger: unknown group")
    flt = trig.get("filter") or []
    try:
        if flt:
            flt = cond.validate("all", flt)
            for c in flt:
                _pill_allowed(c["left"], ttype, {}, managed)
                taint(c["left"])
                for p in tpl.pills_in(c["value"]):
                    _pill_allowed(p, ttype, {}, managed)
                    taint(p)
    except tpl.TemplateError as e:
        raise DefinitionError(f"trigger filter: {e}")

    used: set = set()
    count = [0]
    variables: set = set()
    mode = {"handler": False, "loop": False}

    def walk(steps: Any, depth: int) -> List[dict]:
        if not isinstance(steps, list):
            raise DefinitionError("steps must be a list")
        out = []
        for st in steps:
            count[0] += 1
            if count[0] > MAX_STEPS:
                raise DefinitionError(f"at most {MAX_STEPS} steps")
            if not isinstance(st, dict) or set(st) - {"id", "type", "name", "note", "config", "on_error", "max_attempts", "then", "else"}:
                raise DefinitionError("a step has unknown fields")
            sid, stype = st.get("id"), st.get("type")
            if not isinstance(sid, str) or not _ID.match(sid):
                raise DefinitionError("step ids must look like s1, notify_admin (lowercase letters, digits, _)")
            if sid in used:
                raise DefinitionError(f"duplicate step id '{sid}'")
            if stype not in STEP_TYPES:
                raise DefinitionError(f"step '{sid}': unknown type '{stype}'")
            where = f"step '{sid}'"
            cfg = _pyd(STEP_CFG[stype], st.get("config") or {}, where)
            on_error = st.get("on_error", "fail")
            attempts = st.get("max_attempts", 3)
            if on_error not in ("fail", "continue"):
                raise DefinitionError(f"{where}: on_error must be 'fail' or 'continue'")
            if not isinstance(attempts, int) or isinstance(attempts, bool) or not 1 <= attempts <= 5:
                raise DefinitionError(f"{where}: max_attempts must be 1-5")
            name = st.get("name")
            if name is not None and (not isinstance(name, str) or len(name) > 100):
                raise DefinitionError(f"{where}: name is too long")
            try:
                _check_step(db, stype, cfg, ttype, dict(seen), managed, taint, where, mode["handler"], mode["loop"], actor)
            except tpl.TemplateError as e:
                raise DefinitionError(f"{where}: {e}")
            note = st.get("note")
            if note is not None and (not isinstance(note, str) or len(note) > 300):
                raise DefinitionError(f"{where}: the note is too long (300 characters at most)")
            node = {"id": sid, "type": stype, "name": name, "config": cfg, "on_error": on_error, "max_attempts": attempts}
            if note and note.strip():
                node["note"] = note.strip()   # display only: never resolved, never sent anywhere
            seen[sid] = stype
            used.add(sid)
            if stype == "lookup_row" and not lookup.get_table(db, cfg["table"]).admin_managed:
                seen["$taint:" + sid] = "lookup"   # everything it returns is treated as user-editable
            if stype == "set_variable":
                variables.add(cfg["name"])
                if len(variables) > MAX_VARIABLES:
                    raise DefinitionError(f"at most {MAX_VARIABLES} variables")
                seen["$var:" + cfg["name"]] = "variable"
            elif stype in ("wait", "throttle") and mode["handler"]:
                raise DefinitionError(f"{where}: the error handler cannot wait or throttle")
            if stype == "wait" and cfg["amount"] * WAIT_UNIT_MINUTES[cfg["unit"]] > MAX_WAIT_MINUTES:
                raise DefinitionError(f"{where}: wait at most 7 days")
            if stype == "condition":
                if depth >= MAX_NESTING:
                    raise DefinitionError(f"conditions can be nested at most {MAX_NESTING} deep")
                try:
                    cfg["conditions"] = cond.validate(cfg["match"], cfg["conditions"])
                    for c in cfg["conditions"]:
                        _pill_allowed(c["left"], ttype, seen, managed, mode["handler"], mode["loop"])
                        taint(c["left"])
                        for p in tpl.pills_in(c["value"]):
                            _pill_allowed(p, ttype, seen, managed, mode["handler"], mode["loop"])
                            taint(p)
                except tpl.TemplateError as e:
                    raise DefinitionError(f"{where}: {e}")
                node["then"] = walk(st.get("then") or [], depth + 1)
                node["else"] = walk(st.get("else") or [], depth + 1)
            elif stype == "approval":
                if depth >= MAX_NESTING:
                    raise DefinitionError(f"branches can be nested at most {MAX_NESTING} deep")
                if mode["handler"]:
                    raise DefinitionError(f"{where}: the error handler cannot wait for approvals")
                node["then"] = walk(st.get("then") or [], depth + 1)   # approved
                node["else"] = walk(st.get("else") or [], depth + 1)   # denied or timed out
            elif stype == "for_each_member":
                if mode["loop"]:
                    raise DefinitionError(f"{where}: loops cannot be nested")
                if mode["handler"]:
                    raise DefinitionError(f"{where}: the error handler cannot loop")
                if st.get("else"):
                    raise DefinitionError(f"{where}: a loop has only a body")
                mode["loop"] = True
                try:
                    node["then"] = walk(st.get("then") or [], depth + 1)
                finally:
                    mode["loop"] = False
                if for_publish and not node["then"]:
                    raise DefinitionError(f"{where}: add at least one step inside the loop")
            elif st.get("then") or st.get("else"):
                raise DefinitionError(f"{where}: only conditions, approvals and loops have nested steps")
            out.append(node)
        return out

    steps = walk(definition.get("steps", []), 0)
    if for_publish and not steps:
        raise DefinitionError("add at least one step before publishing")
    out = {"trigger": {"type": ttype, "config": tcfg, "filter": flt}, "steps": steps}
    handler_steps = definition.get("on_error") or []
    if handler_steps:
        # the handler sees the trigger and the error, not the outputs of the main steps (which of them ran is unknown)
        mode["handler"] = True
        seen.clear()
        out["on_error"] = walk(handler_steps, 0)
        mode["handler"] = False
    return out


def _check_lookup(db, stype, cfg) -> None:
    t = lookup.get_table(db, cfg["table"])
    if t is None:
        raise tpl.TemplateError(f"unknown lookup table '{cfg['table']}'")
    cols = lookup.column_types(t)
    if stype == "lookup_row":
        if cfg["column"] not in cols:
            raise tpl.TemplateError(f"the table '{t.name}' has no column '{cfg['column']}'")
        return
    if t.admin_managed:
        raise tpl.TemplateError(f"the table '{t.name}' is administrator-managed: only administrators change its rows (turn that off to let recipes write to it)")
    action = cfg["action"]
    unknown = [c for c in cfg["values"] if c not in cols]
    if unknown:
        raise tpl.TemplateError(f"the table '{t.name}' has no column '{unknown[0]}'")
    if len(cfg["values"]) > lookup.MAX_COLUMNS:
        raise tpl.TemplateError("too many values")
    if action in ("add", "upsert") and not cfg["values"]:
        raise tpl.TemplateError("give at least one column value")
    if action in ("upsert", "delete") and not t.key_column:
        raise tpl.TemplateError(f"the table '{t.name}' has no key column, so rows cannot be {'updated' if action == 'upsert' else 'deleted'} by key")
    if action == "upsert" and t.key_column not in cfg["values"]:
        raise tpl.TemplateError(f"an upsert needs a value for the key column '{t.key_column}'")
    if action == "add" and t.key_column and t.key_column not in cfg["values"]:
        raise tpl.TemplateError(f"a new row needs a value for the key column '{t.key_column}'")
    if action == "delete" and not cfg["key"].strip():
        raise tpl.TemplateError("give the key of the row to delete")


def _check_connection_use(db, cfg, actor) -> None:
    from backend.app.recipes.access import can_use_connection

    cid = cfg.get("connection_id")
    if cid is None or actor is None:
        return
    c = db.get(RecipeConnection, cid)
    if c is not None and not can_use_connection(actor, c):
        raise tpl.TemplateError(f"you are not allowed to use the connection '{c.name}'")


def _check_step(db, stype, cfg, ttype, earlier, managed, taint, where, handler=False, in_loop=False, actor=None) -> None:
    _check_connection_use(db, cfg, actor)
    if stype in ("condition",):
        return
    for p in tpl.all_pills({k: v for k, v in cfg.items() if k not in ("connection_id", "name", "unit", "when_full")}):
        _pill_allowed(p, ttype, earlier, managed, handler, in_loop)
        if stype in STATE_CHANGING or stype in ("set_variable", "lookup_row"):   # a variable must not carry user-editable text onward; a lookup key picks what is read
            taint(p)
    if stype in ("add_to_group", "remove_from_group"):
        g = db.get(Group, cfg["group_id"])
        if g is None:
            raise tpl.TemplateError("unknown group")
        if g.is_system_group:
            raise tpl.TemplateError("system groups cannot be changed by recipes")
    elif stype in ("lookup_row", "lookup_write"):
        _check_lookup(db, stype, cfg)
    elif stype == "for_each_member":
        g = db.get(Group, cfg["group_id"])
        if g is None:
            raise tpl.TemplateError("unknown group")
    elif stype == "set_attribute":
        if cfg["attribute"] not in managed:
            raise tpl.TemplateError(
                f"'{cfg['attribute']}' is not an administrator-managed profile attribute; recipes can only set those"
            )
    elif stype == "send_slack":
        c = db.get(RecipeConnection, cfg["connection_id"])
        if c is None or c.kind != "slack_webhook":
            raise tpl.TemplateError("choose a Slack webhook connection")
    elif stype == "http_request":
        if cfg.get("connection_id") is not None:
            c = db.get(RecipeConnection, cfg["connection_id"])
            if c is not None and c.kind == "slack_webhook":
                raise tpl.TemplateError("Slack connections can only be used by the Slack step")
        for k in cfg["headers"]:
            if len(cfg["headers"]) > 10:
                raise tpl.TemplateError("at most 10 headers")
        if cfg.get("connection_id") is not None:
            if db.get(RecipeConnection, cfg["connection_id"]) is None:
                raise tpl.TemplateError("unknown connection")


# compilation -----------------------------------------------------------------------------------------

def compile_program(steps: List[dict]) -> List[dict]:
    """Flatten nested branches into a list of instructions with absolute jump targets."""
    prog: List[dict] = []

    def emit(items: List[dict]) -> None:
        for st in items:
            if st["type"] == "for_each_member":
                head_pc = len(prog)
                head = {**st, "end_to": 0}
                prog.append(head)
                emit(st.get("then", []))
                prog.append({"type": "loop_next", "id": "", "loop_pc": head_pc})
                head["end_to"] = len(prog)
                continue
            if st["type"] not in BRANCHING:
                prog.append(st)
                continue
            instr = {**st, "true_to": 0, "false_to": 0}
            prog.append(instr)
            instr["true_to"] = len(prog)
            emit(st.get("then", []))
            if st.get("else"):
                jump = {"type": "jump", "id": "", "to": 0}
                prog.append(jump)
                instr["false_to"] = len(prog)
                emit(st["else"])
                jump["to"] = len(prog)
            else:
                instr["false_to"] = len(prog)

    emit(steps)
    return prog


def blank_definition() -> Dict[str, Any]:
    return {"trigger": {"type": "manual", "config": {}, "filter": []}, "steps": []}
