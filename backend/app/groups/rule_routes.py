"""Admin API for group rules (edition feature flag GROUP_RULES_ENABLED)."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi.responses import JSONResponse
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.admin_roles import resolve as role_resolve
from backend.app.auth.deps import require_admin
from backend.app.db import get_db
from backend.app.groups import rules as svc
from backend.app.groups.model import Group
from backend.app.groups.rules import GroupRule, rule_targets
from backend.app.users.model import User


def _enabled():
    if not svc.feature_enabled():
        raise HTTPException(status_code=404, detail="Group rules are not enabled")


router = APIRouter(prefix="/admin/group-rules", tags=["group-rules"], dependencies=[Depends(_enabled)])
features_router = APIRouter(prefix="/admin", tags=["features"])


@features_router.get("/features")
def features(_: User = Depends(require_admin)):
    return {"group_rules": svc.feature_enabled()}


class RuleBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    kind: str = Field("basic", pattern="^(basic|expression)$")
    match: str = "all"
    conditions: List[Dict[str, Any]] = Field(default_factory=list)
    expression: Optional[str] = Field(None, max_length=1000)  # Okta Expression Language, when kind == "expression"
    group_ids: List[int] = Field(..., min_length=1, max_length=10)


class PreviewBody(BaseModel):
    kind: str = Field("basic", pattern="^(basic|expression)$")
    match: str = "all"
    conditions: List[Dict[str, Any]] = Field(default_factory=list)
    expression: Optional[str] = Field(None, max_length=1000)


def _clean(db: Session, body):
    """Validate either kind. Returns (conditions, expression_text); conditions is [] for expression rules."""
    try:
        if body.kind == "expression":
            return [], svc.validate_expression(db, body.expression or "")
        return svc.validate_conditions(db, body.match, body.conditions), None
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


def _targets(db: Session, group_ids: List[int]) -> List[int]:
    ids = sorted(set(group_ids))
    found = {g.id: g for g in db.query(Group).filter(Group.id.in_(ids)).all()}
    if len(found) != len(ids):
        raise HTTPException(status_code=422, detail="Unknown group")
    if any(g.is_system_group for g in found.values()):
        raise HTTPException(status_code=422, detail="System groups cannot be targets of a rule")
    return ids


def _rule_or_404(db: Session, rule_id: int) -> GroupRule:
    r = db.get(GroupRule, rule_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    return r


def _set_targets(db: Session, rule: GroupRule, ids: List[int]) -> None:
    db.execute(rule_targets.delete().where(rule_targets.c.rule_id == rule.id))
    db.execute(insert(rule_targets), [{"rule_id": rule.id, "group_id": i} for i in ids])


@router.get("")
def list_rules(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    rows = db.query(GroupRule).order_by(GroupRule.id).all()
    return {"items": [r.to_dict(db) for r in rows]}


def _camel(key: str) -> str:
    head, *rest = key.split("_")
    return head + "".join(w.capitalize() for w in rest)


@router.get("/expression-help")
def expression_help(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Everything the expression editor suggests: functions, operators, and the attributes a rule may read (never the ones users edit themselves)."""
    from backend.app.groups import okta_el
    from backend.app.profiles import catalog as profile_catalog

    usable = [{"name": "email", "label": "Email", "type": "string"}, {"name": "login", "label": "Username", "type": "string"},
              {"name": "status", "label": "Account status", "type": "enum"}]
    blocked = [{"name": "firstName", "reason": "users can edit this themselves"}, {"name": "lastName", "reason": "users can edit this themselves"}]
    for a in profile_catalog.catalog(db):
        item = {"name": _camel(a.key), "label": a.display_name, "type": a.data_type}
        if a.user_editable:
            blocked.append({"name": item["name"], "reason": "users can edit this themselves"})
        else:
            usable.append(item)
    return {**okta_el.help_catalog(), "attributes": usable, "blocked_attributes": blocked}


class ExpressionBody(BaseModel):
    expression: str = Field("", max_length=2000)


@router.post("/validate-expression")
def validate_expression(body: ExpressionBody, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Live check for the editor: does it parse, is it true/false, does it only read attributes a rule may read?"""
    from backend.app.groups import okta_el

    try:
        text = svc.validate_expression(db, body.expression)
    except ValueError as e:
        return {"ok": False, "error": str(e), "attributes": []}
    return {"ok": True, "error": None, "attributes": sorted(okta_el.attributes(okta_el.parse(text)))}


@router.post("/preview")
def preview(body: PreviewBody, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    conditions, expression = _clean(db, body)
    return svc.preview(db, body.match, conditions, expression=expression)


@router.post("", status_code=201)
def create_rule(body: RuleBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    conditions, expression = _clean(db, body)
    ids = _targets(db, body.group_ids)
    role_resolve.guard_role_groups(db, ids, actor)
    if db.query(func.count(GroupRule.id)).scalar() >= svc.MAX_RULES:
        raise HTTPException(status_code=409, detail=f"At most {svc.MAX_RULES} rules")
    rule = GroupRule(name=body.name.strip(), match=body.match, conditions=conditions, status="inactive",
                     kind=body.kind, expression_text=expression)
    db.add(rule)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Rule name already in use")
    _set_targets(db, rule, ids)
    record(db, AuditAction.GROUP_RULE_CREATED, request, actor, rule.id, "group_rule", {"name": rule.name})
    db.commit()
    return rule.to_dict(db)


# ---- template / export / import ---------------------------------------------------------

FORMAT = "identityforge.group-rules"
FORMAT_VERSION = 1
MAX_IMPORT_RULES = 50

TEMPLATE = {
    "format": FORMAT,
    "version": FORMAT_VERSION,
    "_help": [
        "Edit this file and upload it on the Group rules page (Import). Rules are always created INACTIVE; review and activate them.",
        "kind 'basic': conditions[] with operators equals, not_equals, starts_with, ends_with, contains, is_set, is_not_set; match is 'all' or 'any'.",
        "kind 'expression': an Okta Expression Language boolean in 'expression', e.g. user.department == \"Sales\" && user.userType != \"Contractor\".",
        "Expressions support user.<attribute> (Okta camelCase or snake_case), == != < <= > >= && || ! ?:, and String.* / Arrays.* / Convert.toInt functions.",
        "Only attributes that users cannot edit themselves may be used: email, username (login), status and the admin-managed profile attributes.",
        "'groups' are group NAMES. Import with 'create missing groups' to create any that do not exist yet.",
    ],
    "rules": [
        {"name": "Sales department", "kind": "basic", "match": "all",
         "conditions": [{"attribute": "department", "operator": "equals", "value": "Sales"}], "groups": ["Sales team"]},
        {"name": "Full-time employees in Engineering", "kind": "expression",
         "expression": "user.department == \"Engineering\" && user.userType == \"Employee\"", "groups": ["Engineering"]},
        {"name": "Company email addresses", "kind": "expression",
         "expression": "String.stringContains(user.email, \"@example.com\") && user.userType != \"Contractor\"", "groups": ["All staff"]},
        {"name": "Any of two cost centers", "kind": "basic", "match": "any",
         "conditions": [{"attribute": "cost_center", "operator": "equals", "value": "C100"},
                        {"attribute": "cost_center", "operator": "equals", "value": "C200"}], "groups": ["Finance"]},
    ],
}


def _export_rule(db: Session, r: GroupRule) -> dict:
    d = r.to_dict(db)
    out: Dict[str, Any] = {"name": r.name, "kind": r.kind, "groups": [g["name"] for g in d["groups"]]}
    if r.kind == "expression":
        out["expression"] = r.expression_text
    else:
        out["match"] = r.match
        out["conditions"] = r.conditions
    return out


@router.get("/template")
def download_template(_: User = Depends(require_admin)):
    return JSONResponse(TEMPLATE, headers={"Content-Disposition": 'attachment; filename="group-rules-template.json"'})


@router.get("/export")
def export_rules(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    rules = db.query(GroupRule).order_by(GroupRule.id).all()
    doc = {"format": FORMAT, "version": FORMAT_VERSION, "rules": [_export_rule(db, r) for r in rules]}
    return JSONResponse(doc, headers={"Content-Disposition": 'attachment; filename="group-rules.json"'})


class ImportBody(BaseModel):
    document: Dict[str, Any]
    create_missing_groups: bool = False
    dry_run: bool = False


@router.post("/import")
def import_rules(body: ImportBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    """Create rules from a template/export file. Everything is validated first; nothing is created if any rule is
    invalid (all-or-nothing). Rules arrive INACTIVE, so importing never changes anyone's membership."""
    doc = body.document
    if doc.get("format") != FORMAT or doc.get("version") != FORMAT_VERSION:
        raise HTTPException(status_code=422, detail=f"Not a {FORMAT} v{FORMAT_VERSION} file")
    items = doc.get("rules")
    if not isinstance(items, list) or not items or len(items) > MAX_IMPORT_RULES:
        raise HTTPException(status_code=422, detail=f"'rules' must be a list of 1 to {MAX_IMPORT_RULES} rules")
    existing_names = {n.lower() for (n,) in db.query(GroupRule.name).all()}
    if db.query(func.count(GroupRule.id)).scalar() + len(items) > svc.MAX_RULES:
        raise HTTPException(status_code=409, detail=f"At most {svc.MAX_RULES} rules")
    groups = {g.name.lower(): g for g in db.query(Group).all()}
    errors, planned, new_groups, seen = [], [], set(), set()
    for i, raw in enumerate(items, 1):
        label = f"rule {i}"
        try:
            if not isinstance(raw, dict):
                raise ValueError("must be an object")
            name = str(raw.get("name", "")).strip()
            if not name or len(name) > 100:
                raise ValueError("needs a name of 1 to 100 characters")
            label = f"rule {i} ({name})"
            if name.lower() in existing_names or name.lower() in seen:
                raise ValueError("a rule with this name already exists")
            seen.add(name.lower())
            kind = raw.get("kind", "basic")
            if kind not in ("basic", "expression"):
                raise ValueError("kind must be 'basic' or 'expression'")
            names = raw.get("groups")
            if not isinstance(names, list) or not names or len(names) > 10 or not all(isinstance(n, str) and n.strip() for n in names):
                raise ValueError("'groups' must list 1 to 10 group names")
            targets = []
            for gn in names:
                g = groups.get(gn.strip().lower())
                if g is None:
                    if not body.create_missing_groups:
                        raise ValueError(f"group '{gn}' does not exist (import with 'create missing groups' to create it)")
                    new_groups.add(gn.strip())
                elif g.is_system_group:
                    raise ValueError(f"group '{gn}' is a system group")
                targets.append(gn.strip())
            if kind == "expression":
                conditions, expression, match = [], svc.validate_expression(db, raw.get("expression", "")), "all"
            else:
                match = raw.get("match", "all")
                conditions, expression = svc.validate_conditions(db, match, raw.get("conditions") or []), None
            planned.append((name, kind, match, conditions, expression, targets))
        except ValueError as e:
            errors.append(f"{label}: {e}")
    if errors:
        raise HTTPException(status_code=422, detail={"message": "Import refused; nothing was created", "errors": errors})
    role_resolve.guard_role_groups(db, [groups[t.lower()].id for *_, ts in planned for t in ts if t.lower() in groups], actor)
    if body.dry_run:
        return {"dry_run": True, "rules": len(planned), "groups_to_create": sorted(new_groups)}
    for gn in sorted(new_groups):
        g = Group(name=gn)
        db.add(g)
        db.flush()
        groups[gn.lower()] = g
        record(db, AuditAction.GROUP_CREATED, request, actor, g.id, "group", {"name": gn, "via": "rule_import"})
    created = []
    for name, kind, match, conditions, expression, targets in planned:
        rule = GroupRule(name=name, kind=kind, match=match, conditions=conditions, expression_text=expression, status="inactive")
        db.add(rule)
        db.flush()
        _set_targets(db, rule, sorted({groups[t.lower()].id for t in targets}))
        record(db, AuditAction.GROUP_RULE_CREATED, request, actor, rule.id, "group_rule", {"name": name, "via": "import"})
        created.append(rule.id)
    db.commit()
    return {"dry_run": False, "created": created, "groups_created": sorted(new_groups)}


@router.get("/{rule_id}")
def get_rule(rule_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return _rule_or_404(db, rule_id).to_dict(db)


@router.put("/{rule_id}")
def update_rule(
    rule_id: int, body: RuleBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)
):
    rule = _rule_or_404(db, rule_id)
    if rule.status == "active":
        raise HTTPException(status_code=409, detail="Deactivate the rule before editing it")
    role_resolve.guard_role_groups(db, rule.target_ids(db) + _targets(db, body.group_ids), actor)
    rule.conditions, rule.expression_text = _clean(db, body)
    rule.kind = body.kind
    rule.match = body.match
    rule.name = body.name.strip()
    rule.updated_at = datetime.now(timezone.utc)
    _set_targets(db, rule, _targets(db, body.group_ids))
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Rule name already in use")
    record(db, AuditAction.GROUP_RULE_UPDATED, request, actor, rule.id, "group_rule", {"name": rule.name})
    db.commit()
    return rule.to_dict(db)


@router.post("/{rule_id}/activate")
def activate(rule_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    rule = _rule_or_404(db, rule_id)
    role_resolve.guard_role_groups(db, rule.target_ids(db), actor)
    rule.status = "active"
    result = svc.evaluate_rule(db, rule, request, actor)
    record(db, AuditAction.GROUP_RULE_ACTIVATED, request, actor, rule.id, "group_rule", result)
    db.commit()
    return {**rule.to_dict(db), "applied": result}


@router.post("/{rule_id}/deactivate")
def deactivate(rule_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    rule = _rule_or_404(db, rule_id)
    role_resolve.guard_role_groups(db, rule.target_ids(db), actor)
    rule.status = "inactive"
    removed = svc.strip_rule_memberships(db, rule, request, actor)
    record(db, AuditAction.GROUP_RULE_DEACTIVATED, request, actor, rule.id, "group_rule", {"removed": removed})
    db.commit()
    return {**rule.to_dict(db), "removed": removed}


@router.delete("/{rule_id}")
def delete_rule(rule_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    rule = _rule_or_404(db, rule_id)
    role_resolve.guard_role_groups(db, rule.target_ids(db), actor)
    removed = svc.strip_rule_memberships(db, rule, request, actor)
    name = rule.name
    db.delete(rule)
    record(db, AuditAction.GROUP_RULE_DELETED, request, actor, rule_id, "group_rule", {"name": name, "removed": removed})
    db.commit()
    return {"success": True, "removed": removed}
