"""Group rules: attribute-based automatic membership (Okta-style "group rules").

A rule says: for users matching these conditions, be a member of these groups. The platform keeps those
memberships in sync when a rule is activated and whenever a user is created or changed.

Security design (memberships may later drive authorization, so this must not become a privilege-escalation path):
- Conditions may only use attributes the *user cannot edit themselves*: email, username, status and
  admin-managed profile attributes. Self-editable fields (names, phone, title, location, timezone, locale, bio)
  are refused, otherwise a user could edit their way into a group.
- Conditions are structured data evaluated by this module; there is no expression language and no eval.
- Memberships created by a rule are tagged with the rule id. Manual memberships are never touched by rules,
  and a rule-managed membership cannot be removed by hand (change the rule or the user instead).
- Deactivating or deleting a rule removes the memberships it created (deny by default).
- Only active users match.
"""

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Table, UniqueConstraint, delete, insert, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.config import settings
from backend.app.db import Base
from backend.app.groups.model import Group, user_group_association
from backend.app.profiles.schemas import SELF_EDITABLE
from backend.app.tenancy import TenantOwned
from backend.app.users.model import User

FIXED_ATTRIBUTES = ("email", "username", "status")
OPERATORS = ("equals", "not_equals", "starts_with", "ends_with", "contains", "is_set", "is_not_set")
MAX_CONDITIONS = 10
MAX_RULES = 100
_KEY = re.compile(r"^[a-z][a-z0-9_]{0,49}$")

rule_targets = Table(
    "group_rule_targets",
    Base.metadata,
    Column("rule_id", Integer, ForeignKey("group_rules.id", ondelete="CASCADE"), primary_key=True),
    Column("group_id", Integer, ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True),
)


class GroupRule(TenantOwned, Base):
    __tablename__ = "group_rules"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_group_rules_tenant_name"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    status = Column(String(16), nullable=False, default="inactive")  # inactive | active
    match = Column(String(3), nullable=False, default="all")  # all | any
    conditions = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    def target_ids(self, db: Session) -> List[int]:
        return [r[0] for r in db.execute(select(rule_targets.c.group_id).where(rule_targets.c.rule_id == self.id))]

    def to_dict(self, db: Session) -> dict:
        ids = self.target_ids(db)
        groups = db.query(Group.id, Group.name).filter(Group.id.in_(ids)).all() if ids else []
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "match": self.match,
            "conditions": self.conditions,
            "expression": describe(self.match, self.conditions),
            "groups": [{"id": g.id, "name": g.name} for g in groups],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


# ---- validation ------------------------------------------------------------------------

def feature_enabled() -> bool:
    return bool(settings.GROUP_RULES_ENABLED)


def validate_conditions(match: str, conditions: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Return the normalised conditions or raise ValueError with a user-facing message."""
    if match not in ("all", "any"):
        raise ValueError("match must be 'all' or 'any'")
    if not conditions:
        raise ValueError("a rule needs at least one condition")
    if len(conditions) > MAX_CONDITIONS:
        raise ValueError(f"at most {MAX_CONDITIONS} conditions")
    out = []
    for c in conditions:
        attr, op = str(c.get("attribute", "")).strip().lower(), c.get("operator")
        value = c.get("value", "")
        if attr in SELF_EDITABLE or attr in ("first_name", "last_name"):
            raise ValueError(f"'{attr}' can be edited by users themselves, so it cannot be used in a rule")
        if attr not in FIXED_ATTRIBUTES and not _KEY.match(attr):
            raise ValueError(f"invalid attribute '{attr}'")
        if op not in OPERATORS:
            raise ValueError(f"unknown operator '{op}'")
        if op in ("is_set", "is_not_set"):
            value = ""
        elif not isinstance(value, str) or not value.strip() or len(value) > 200:
            raise ValueError(f"'{attr}' needs a value of up to 200 characters")
        out.append({"attribute": attr, "operator": op, "value": value.strip()})
    return out


def describe(match: str, conditions: List[Dict[str, str]]) -> str:
    """Human-readable form, e.g.  user.department equals "Sales" AND user.status equals "active"."""
    parts = []
    for c in conditions:
        a = f"user.{c['attribute']}"
        parts.append(f"{a} {c['operator'].replace('_', ' ')}" + (f' "{c["value"]}"' if c["operator"] not in ("is_set", "is_not_set") else ""))
    return (" AND " if match == "all" else " OR ").join(parts)


# ---- evaluation ------------------------------------------------------------------------

def _value(user: User, attribute: str) -> Optional[str]:
    if attribute in FIXED_ATTRIBUTES:
        v = getattr(user, attribute, None)
    else:
        v = user.get_profile_attributes().get(attribute)
    return None if v is None or v == "" else str(v)


def _cond_matches(user: User, c: Dict[str, str]) -> bool:
    actual, op = _value(user, c["attribute"]), c["operator"]
    if op == "is_set":
        return actual is not None
    if op == "is_not_set":
        return actual is None
    want = c["value"].lower()
    have = (actual or "").lower()
    if op == "equals":
        return actual is not None and have == want
    if op == "not_equals":
        return actual is None or have != want
    if actual is None:
        return False
    return {"starts_with": have.startswith, "ends_with": have.endswith, "contains": lambda w: w in have}[op](want)


def matches(rule_match: str, conditions: List[Dict[str, str]], user: User) -> bool:
    if user.status != "active":
        return False
    results = (_cond_matches(user, c) for c in conditions)
    return all(results) if rule_match == "all" else any(results)


def _recount(db: Session, group_id: int) -> None:
    g = db.get(Group, group_id)
    if g is not None:
        db.flush()
        db.expire(g, ["members"])
        g.member_count = len(g.members)


def _reconcile(db: Session, rule: GroupRule, user: User, should_be_member: bool, request, actor) -> Dict[str, int]:
    """Make this user's rule-managed memberships agree with the rule. Never touches manual memberships."""
    added = removed = 0
    for gid in rule.target_ids(db):
        row = db.execute(
            select(user_group_association.c.rule_id).where(
                user_group_association.c.user_id == user.id, user_group_association.c.group_id == gid
            )
        ).first()
        if should_be_member and row is None:
            db.execute(insert(user_group_association).values(
                user_id=user.id, group_id=gid, added_by_user_id=None, rule_id=rule.id,
                added_at=datetime.now(timezone.utc),
            ))
            record(db, AuditAction.GROUP_MEMBER_ADDED, request, actor, gid, "group", {"user_id": user.id, "via_rule": rule.id})
            _recount(db, gid)
            added += 1
        elif not should_be_member and row is not None and row[0] == rule.id:
            db.execute(delete(user_group_association).where(
                user_group_association.c.user_id == user.id, user_group_association.c.group_id == gid,
                user_group_association.c.rule_id == rule.id,
            ))
            record(db, AuditAction.GROUP_MEMBER_REMOVED, request, actor, gid, "group", {"user_id": user.id, "via_rule": rule.id})
            _recount(db, gid)
            removed += 1
    return {"added": added, "removed": removed}


def evaluate_user(db: Session, user: User, request=None, actor=None) -> None:
    """Re-evaluate every active rule for one user (call after create/update; caller commits)."""
    if not feature_enabled():
        return
    for rule in db.query(GroupRule).filter(GroupRule.status == "active").all():
        _reconcile(db, rule, user, matches(rule.match, rule.conditions, user), request, actor)


def evaluate_rule(db: Session, rule: GroupRule, request=None, actor=None) -> Dict[str, int]:
    """Apply one rule to every user (activation, or a changed rule). Caller commits."""
    total = {"added": 0, "removed": 0}
    if rule.status != "active":
        return total
    for user in db.query(User).yield_per(200):
        r = _reconcile(db, rule, user, matches(rule.match, rule.conditions, user), request, actor)
        total["added"] += r["added"]
        total["removed"] += r["removed"]
    return total


def strip_rule_memberships(db: Session, rule: GroupRule, request=None, actor=None) -> int:
    """Remove every membership this rule created (deactivate/delete)."""
    rows = db.execute(
        select(user_group_association.c.user_id, user_group_association.c.group_id).where(
            user_group_association.c.rule_id == rule.id
        )
    ).all()
    db.execute(delete(user_group_association).where(user_group_association.c.rule_id == rule.id))
    for uid, gid in rows:
        record(db, AuditAction.GROUP_MEMBER_REMOVED, request, actor, gid, "group", {"user_id": uid, "via_rule": rule.id})
    for gid in {g for _, g in rows}:
        _recount(db, gid)
    return len(rows)


def preview(db: Session, match: str, conditions: List[Dict[str, str]], limit: int = 10) -> Dict[str, Any]:
    hits = [u for u in db.query(User).all() if matches(match, conditions, u)]
    return {
        "count": len(hits),
        "sample": [{"id": u.id, "email": u.email, "first_name": u.first_name, "last_name": u.last_name} for u in hits[:limit]],
    }
