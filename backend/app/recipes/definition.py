"""Recipe definitions: validation, the datapill catalog, and compilation to a flat program (ADR 008 D2).

Definition JSON::

    {"trigger": {"type": "user.created", "config": {}, "filter": [{"left": "...", "operator": "...", "value": "..."}]},
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
from backend.app.recipes import templates as tpl
from backend.app.recipes.models import RecipeConnection

MAX_STEPS = 30
MAX_NESTING = 3
MAX_DEFINITION_BYTES = 65536
_ID = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

EVENT_TRIGGERS = (
    "user.created", "user.activated", "user.deactivated", "user.updated", "user.attribute_changed",
    "group.member_added", "group.member_removed", "login.failed",
)
TRIGGER_TYPES = EVENT_TRIGGERS + ("schedule", "manual", "webhook")
ACTION_TYPES = (
    "add_to_group", "remove_from_group", "set_attribute", "activate_user", "deactivate_user", "http_request", "log",
)
STEP_TYPES = ACTION_TYPES + ("condition", "stop")
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


class _TrigLogin(_Cfg):
    min_failures: int = Field(1, ge=1, le=100)


class _TrigSchedule(_Cfg):
    interval_minutes: int = Field(..., ge=5, le=1440)


TRIGGER_CFG = {
    **{t: _TrigNone for t in ("user.created", "user.activated", "user.deactivated", "user.updated", "manual", "webhook")},
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


class _Log(_Cfg):
    message: str = Field(..., min_length=1, max_length=1000)


class _Condition(_Cfg):
    match: Literal["all", "any"] = "all"
    conditions: List[Dict[str, Any]]


class _Stop(_Cfg):
    outcome: Literal["success", "failed"] = "success"
    message: str = Field("", max_length=500)


STEP_CFG = {
    "add_to_group": _AddRemove, "remove_from_group": _AddRemove, "set_attribute": _SetAttr,
    "activate_user": _UserOnly, "deactivate_user": _UserOnly, "http_request": _Http, "log": _Log,
    "condition": _Condition, "stop": _Stop,
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
    "login.failed": _COMMON + _USER + [("trigger.login.consecutive_failures", "Consecutive failures")],
    "schedule": _COMMON + [("trigger.schedule.scheduled_for", "Scheduled for")],
    "manual": _COMMON + _USER + [("trigger.manual.started_by", "Started by (admin id)")],
    "webhook": _COMMON,
}
_DYNAMIC_PREFIXES = {  # any suffix is allowed below these
    "trigger.user.attributes.": ("user.created", "user.activated", "user.deactivated", "user.updated",
                                 "user.attribute_changed", "group.member_added", "group.member_removed",
                                 "login.failed", "manual"),
    "trigger.payload.": ("manual", "webhook"),
}
STEP_OUTPUTS = {
    "add_to_group": ["user_id", "group_id", "changed"], "remove_from_group": ["user_id", "group_id", "changed"],
    "set_attribute": ["user_id", "attribute", "value", "changed"],
    "activate_user": ["user_id", "changed"], "deactivate_user": ["user_id", "changed"],
    "http_request": ["status_code", "ok", "body", "json"], "log": ["message"], "condition": ["result"], "stop": [],
}
_RECIPE_FIELDS = ["recipe.id", "recipe.name", "recipe.version", "job.id"]
_SAFE_USER_FIELDS = {"id", "email", "username", "status"}


def admin_managed_keys(db: Session) -> set:
    return {a.key for a in profile_catalog.catalog(db) if not a.user_editable}


def taint_checker(db: Session) -> Callable[[str], None]:
    """Refuse datapills a user can edit themselves (first/last name, self-editable attributes). ADR 008 D2."""
    managed = admin_managed_keys(db)

    def check(path: str) -> None:
        segs = path.split(".")
        if segs[:2] == ["trigger", "user"]:
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


def _pill_allowed(path: str, trigger_type: str, earlier_steps: Dict[str, str], db_keys: set) -> None:
    segs = path.split(".")
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


def validate_definition(db: Session, definition: Any, *, for_publish: bool = False) -> Dict[str, Any]:
    """Return the normalised definition or raise DefinitionError."""
    import json

    if not isinstance(definition, dict) or set(definition) - {"trigger", "steps"}:
        raise DefinitionError("definition must contain 'trigger' and 'steps' only")
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
    taint = taint_checker(db)
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

    seen: Dict[str, str] = {}
    count = [0]

    def walk(steps: Any, depth: int) -> List[dict]:
        if not isinstance(steps, list):
            raise DefinitionError("steps must be a list")
        out = []
        for st in steps:
            count[0] += 1
            if count[0] > MAX_STEPS:
                raise DefinitionError(f"at most {MAX_STEPS} steps")
            if not isinstance(st, dict) or set(st) - {"id", "type", "name", "config", "on_error", "max_attempts", "then", "else"}:
                raise DefinitionError("a step has unknown fields")
            sid, stype = st.get("id"), st.get("type")
            if not isinstance(sid, str) or not _ID.match(sid):
                raise DefinitionError("step ids must look like s1, notify_admin (lowercase letters, digits, _)")
            if sid in seen:
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
                _check_step(db, stype, cfg, ttype, dict(seen), managed, taint, where)
            except tpl.TemplateError as e:
                raise DefinitionError(f"{where}: {e}")
            node = {"id": sid, "type": stype, "name": name, "config": cfg, "on_error": on_error, "max_attempts": attempts}
            seen[sid] = stype
            if stype == "condition":
                if depth >= MAX_NESTING:
                    raise DefinitionError(f"conditions can be nested at most {MAX_NESTING} deep")
                try:
                    cfg["conditions"] = cond.validate(cfg["match"], cfg["conditions"])
                    for c in cfg["conditions"]:
                        _pill_allowed(c["left"], ttype, seen, managed)
                        taint(c["left"])
                        for p in tpl.pills_in(c["value"]):
                            _pill_allowed(p, ttype, seen, managed)
                            taint(p)
                except tpl.TemplateError as e:
                    raise DefinitionError(f"{where}: {e}")
                node["then"] = walk(st.get("then") or [], depth + 1)
                node["else"] = walk(st.get("else") or [], depth + 1)
            elif st.get("then") or st.get("else"):
                raise DefinitionError(f"{where}: only conditions have branches")
            out.append(node)
        return out

    steps = walk(definition.get("steps", []), 0)
    if for_publish and not steps:
        raise DefinitionError("add at least one step before publishing")
    return {"trigger": {"type": ttype, "config": tcfg, "filter": flt}, "steps": steps}


def _check_step(db, stype, cfg, ttype, earlier, managed, taint, where) -> None:
    if stype in ("condition",):
        return
    for p in tpl.all_pills({k: v for k, v in cfg.items() if k != "connection_id"}):
        _pill_allowed(p, ttype, earlier, managed)
        if stype in STATE_CHANGING:
            taint(p)
    if stype in ("add_to_group", "remove_from_group"):
        g = db.get(Group, cfg["group_id"])
        if g is None:
            raise tpl.TemplateError("unknown group")
        if g.is_system_group:
            raise tpl.TemplateError("system groups cannot be changed by recipes")
    elif stype == "set_attribute":
        if cfg["attribute"] not in managed:
            raise tpl.TemplateError(
                f"'{cfg['attribute']}' is not an administrator-managed profile attribute; recipes can only set those"
            )
    elif stype == "http_request":
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
            if st["type"] != "condition":
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
