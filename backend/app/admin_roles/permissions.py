"""Which administrator role may do what. Pure data and two functions, so the whole policy fits on one screen.

Authorization is decided from the *route template* and HTTP method (GET/HEAD/OPTIONS = read, anything else = write), at the one
dependency every admin endpoint already uses. A route that matches no area needs a full organization administrator (deny by
default), so a new admin endpoint is safe before anyone remembers to classify it.
"""

from typing import Dict, Iterable, Optional

READ, WRITE = "read", "write"
SAFE = {"GET", "HEAD", "OPTIONS"}

# (route-template prefix after /api/v1, area), longest prefix wins
_AREAS = [
    ("/admin/users", "users"),
    ("/admin/groups", "groups"),
    ("/admin/group-rules", "groups"),
    ("/admin/applications", "applications"),
    ("/admin/access-requests", "applications"),
    ("/admin/oidc", "applications"),
    ("/admin/provisioning-apps", "applications"),
    ("/admin/scim", "applications"),
    ("/admin/audit", "reports"),
    ("/admin/stats", "overview"),
    ("/admin/dashboard", "overview"),
    ("/admin/search", "overview"),
    ("/admin/features", "overview"),
    ("/admin/network-zones", "security"),
    ("/admin/security-policy", "security"),
    ("/admin/profile-attributes", "directory_settings"),
    ("/admin/recipes", "automation"),
    ("/admin/recipe-connections", "automation"),
    ("/admin/branding", "branding"),
    ("/admin/email-templates", "branding"),
    ("/admin/roles", "roles"),
]
AREA_NAMES = sorted({a for _, a in _AREAS})

ROLES: Dict[str, dict] = {
    "org_admin": {"label": "Organization administrator", "description": "Full access to every administrator function except assigning roles.",
                  "access": {a: WRITE for a in AREA_NAMES if a != "roles"}},
    "read_only_admin": {"label": "Read-only administrator", "description": "Can view everything an organization administrator can, and change nothing.",
                        "access": {a: READ for a in AREA_NAMES if a != "roles"}},
    "help_desk_admin": {"label": "Help desk administrator", "description": "Resets passwords and factors, suspends, unlocks and activates users. Cannot create or delete users, or change groups and applications.",
                        "access": {"users": WRITE, "groups": READ, "applications": READ, "overview": READ}},
    "app_admin": {"label": "Application administrator", "description": "Creates and manages applications, sign-on settings, assignments and provisioning.",
                  "access": {"applications": WRITE, "users": READ, "groups": READ, "overview": READ}},
    "group_admin": {"label": "Group administrator", "description": "Manages groups, memberships and group rules.",
                    "access": {"groups": WRITE, "users": READ, "overview": READ}},
    "report_admin": {"label": "Report administrator", "description": "Reads the system log and dashboard.",
                     "access": {"reports": READ, "users": READ, "overview": READ}},
}
ROLE_IDS = tuple(ROLES)

# (role, method, template) pairs a role may never use even inside an area it can write
_NEVER = {
    ("help_desk_admin", "POST", "/admin/users"),
    ("help_desk_admin", "DELETE", "/admin/users/{user_id}"),
}


def area_for(template: str) -> Optional[str]:
    best = None
    for prefix, area in _AREAS:
        if (template == prefix or template.startswith(prefix + "/")) and (best is None or len(prefix) > len(best[0])):
            best = (prefix, area)
    return best[1] if best else None


def effective(roles: Iterable[str]) -> Dict[str, str]:
    """Union of the roles' access; no roles at all means a full organization administrator."""
    chosen = [r for r in roles if r in ROLES] or ["org_admin"]
    out: Dict[str, str] = {}
    for r in chosen:
        for area, level in ROLES[r]["access"].items():
            if out.get(area) != WRITE:
                out[area] = level
    return out


def has_access(db, user, area: str) -> bool:
    """Does this admin hold at least read access to `area`? (super admins always do)"""
    if user.is_super_admin:
        return True
    from backend.app.admin_roles.models import AdminRoleAssignment

    roles = [r for (r,) in db.query(AdminRoleAssignment.role).filter(AdminRoleAssignment.user_id == user.id)]
    return area in effective(roles)


def allowed(roles: Iterable[str], method: str, template: str) -> bool:
    chosen = [r for r in roles if r in ROLES] or ["org_admin"]
    area = area_for(template)
    if area is None or area == "roles":
        return False  # unclassified: only super administrators (who never reach here); roles are theirs alone
    need = READ if method.upper() in SAFE else WRITE
    for r in chosen:
        if (r, method.upper(), template) in _NEVER:
            continue
        have = ROLES[r]["access"].get(area)
        if have == WRITE or (have == READ and need == READ):
            return True
    return False
