"""Admin API for group rules (edition feature flag GROUP_RULES_ENABLED)."""

from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
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
    match: str = "all"
    conditions: List[Dict[str, Any]]
    group_ids: List[int] = Field(..., min_length=1, max_length=10)


class PreviewBody(BaseModel):
    match: str = "all"
    conditions: List[Dict[str, Any]]


def _clean(body_match: str, conditions: List[Dict[str, Any]]):
    try:
        return svc.validate_conditions(body_match, conditions)
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


@router.post("/preview")
def preview(body: PreviewBody, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return svc.preview(db, body.match, _clean(body.match, body.conditions))


@router.post("", status_code=201)
def create_rule(body: RuleBody, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    conditions = _clean(body.match, body.conditions)
    ids = _targets(db, body.group_ids)
    if db.query(func.count(GroupRule.id)).scalar() >= svc.MAX_RULES:
        raise HTTPException(status_code=409, detail=f"At most {svc.MAX_RULES} rules")
    rule = GroupRule(name=body.name.strip(), match=body.match, conditions=conditions, status="inactive")
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
    rule.conditions = _clean(body.match, body.conditions)
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
    rule.status = "active"
    result = svc.evaluate_rule(db, rule, request, actor)
    record(db, AuditAction.GROUP_RULE_ACTIVATED, request, actor, rule.id, "group_rule", result)
    db.commit()
    return {**rule.to_dict(db), "applied": result}


@router.post("/{rule_id}/deactivate")
def deactivate(rule_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    rule = _rule_or_404(db, rule_id)
    rule.status = "inactive"
    removed = svc.strip_rule_memberships(db, rule, request, actor)
    record(db, AuditAction.GROUP_RULE_DEACTIVATED, request, actor, rule.id, "group_rule", {"removed": removed})
    db.commit()
    return {**rule.to_dict(db), "removed": removed}


@router.delete("/{rule_id}")
def delete_rule(rule_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    rule = _rule_or_404(db, rule_id)
    removed = svc.strip_rule_memberships(db, rule, request, actor)
    name = rule.name
    db.delete(rule)
    record(db, AuditAction.GROUP_RULE_DELETED, request, actor, rule_id, "group_rule", {"name": name, "removed": removed})
    db.commit()
    return {"success": True, "removed": removed}
