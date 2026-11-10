"""Group standards (ADR 019): what each kind of group is for, what metadata it must carry, and how it is validated.

Machine-readable on purpose (GET /admin/groups/standards) so provisioning tools and AI assistants can create groups that
follow the house rules instead of guessing them.
"""

import re
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

TYPES: Dict[str, Dict[str, Any]] = {
    "team": {
        "label": "Team group",
        "purpose": "People who work together: a department, function or squad. Often kept current by a group rule on HR attributes.",
        "naming": "Team - <name>, e.g. Team - Platform Engineering",
        "requires": ["owner"],
        "can_carry_admin_roles": True,
        "typical_membership": "rule-managed from department / manager / title, or hand-picked for small squads",
    },
    "project": {
        "label": "Project group",
        "purpose": "Time-boxed collaboration across teams. Has an end date and is reviewed or retired then.",
        "naming": "Project - <name>, e.g. Project - Migration 2027",
        "requires": ["owner", "review_by"],
        "can_carry_admin_roles": False,
        "typical_membership": "hand-picked by the owner",
    },
    "app_access": {
        "label": "App access group",
        "purpose": "Entitlement to one application (optionally one role in it). Assign the group to the application, never individual people.",
        "naming": "App - <application> - <role>, e.g. App - Salesforce - Admin",
        "requires": ["owner"],
        "can_carry_admin_roles": False,
        "typical_membership": "populated from team groups or by access requests; reviewed by the owner",
    },
    "role": {
        "label": "Role based group",
        "purpose": "A named role inside an application (Admin, Editor, Viewer). Assign the group to the application, and put people in it by team group, rule or access request.",
        "naming": "Role - <application> - <role>, e.g. Role - Salesforce - Sales Manager",
        "requires": ["owner"],
        "can_carry_admin_roles": True,
        "typical_membership": "derived from team groups or a group rule on job attributes; reviewed by the owner",
    },
    "push": {
        "label": "Push group",
        "purpose": "Mirrored to a downstream application (SCIM / provisioning) so that application can use the group for its own permissions.",
        "naming": "Push - <application> - <name>, e.g. Push - Slack - Engineering",
        "requires": [],
        "can_carry_admin_roles": False,
        "typical_membership": "derived from a team or app access group; do not edit by hand",
    },
    "app": {
        "label": "App group",
        "purpose": "A group that belongs to an integration and is created, named and filled by it. Treat as read-only reference data.",
        "naming": "<application>: <name>, as the application names it",
        "requires": [],
        "can_carry_admin_roles": False,
        "typical_membership": "managed by the application or its importer",
    },
    "other": {
        "label": "Unclassified",
        "purpose": "Existing groups that have not been classified yet. Classify them; new groups should pick a real type.",
        "naming": "no convention",
        "requires": [],
        "can_carry_admin_roles": False,
        "typical_membership": "any",
    },
}
TYPE_IDS = tuple(TYPES)
SENSITIVITY = ("low", "medium", "high")
MAX_TAGS, MAX_ATTRS = 10, 20
TAG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,29}$")
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,49}$")


def document() -> dict:
    return {
        "types": [{"id": k, **v} for k, v in TYPES.items()],
        "sensitivity": list(SENSITIVITY),
        "metadata": {
            "owner_user_id": "A user accountable for the group; required for team, project and app_access groups.",
            "sensitivity": "How damaging wrong membership would be: low, medium or high. Drives review frequency in analytics.",
            "review_by": "ISO date by which the owner must review or retire the group; required for project groups.",
            "tags": f"Up to {MAX_TAGS} lowercase labels (letters, digits, - and _; 30 characters each).",
            "attributes": f"Up to {MAX_ATTRS} free-form string pairs (key snake_case, value up to 200 characters), e.g. cost_center, business_unit, application.",
        },
        "rules": [
            "Admin roles may be attached only to team and role based groups, and only by a super administrator.",
            "Only a super administrator can change who is in a group that carries admin roles.",
            "Prefer assigning app access and role based groups to applications over assigning users.",
        ],
    }


def clean_tags(tags: Optional[List[str]]) -> List[str]:
    out = []
    for t in tags or []:
        t = str(t).strip().lower()
        if not TAG_RE.match(t):
            raise HTTPException(status_code=422, detail=f"Invalid tag {t!r}: lowercase letters, digits, - and _, up to 30 characters")
        if t not in out:
            out.append(t)
    if len(out) > MAX_TAGS:
        raise HTTPException(status_code=422, detail=f"At most {MAX_TAGS} tags")
    return out


def clean_attributes(attrs: Optional[Dict[str, Any]]) -> Dict[str, str]:
    attrs = attrs or {}
    if len(attrs) > MAX_ATTRS:
        raise HTTPException(status_code=422, detail=f"At most {MAX_ATTRS} attributes")
    out = {}
    for k, v in attrs.items():
        if not KEY_RE.match(str(k)):
            raise HTTPException(status_code=422, detail=f"Invalid attribute key {k!r}: snake_case, up to 50 characters")
        if not isinstance(v, str) or len(v) > 200:
            raise HTTPException(status_code=422, detail=f"Attribute {k!r} must be a string of up to 200 characters")
        out[str(k)] = v
    return out


def check_requirements(group_type: str, owner_user_id: Optional[int], review_by: Optional[date]) -> None:
    need = TYPES[group_type]["requires"]
    missing = [n for n, ok in (("owner", owner_user_id is not None), ("review_by", review_by is not None)) if n in need and not ok]
    if missing:
        raise HTTPException(status_code=422, detail=f"A {TYPES[group_type]['label'].lower()} needs: " + ", ".join(missing))
