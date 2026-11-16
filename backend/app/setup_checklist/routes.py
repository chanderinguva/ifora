"""First-run checklist for new administrators (IFORA-42).

Whether an item is done is computed from the real objects on every request, never stored: it ticks itself when the user,
application, policy or zone exists. Only the *dismissal* is stored, per administrator. An item is listed only to an
administrator who may read its area, and the answer carries done/dismissed flags, never counts or content.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.admin_roles import permissions
from backend.app.applications.models import Application
from backend.app.auth.deps import require_admin
from backend.app.branding.models import OrgBranding, OrgLogo
from backend.app.db import get_db
from backend.app.groups.model import Group
from backend.app.policies.models import NetworkZone
from backend.app.security_policy.models import OrgSecurityPolicy
from backend.app.setup_checklist.models import ChecklistDismissal
from backend.app.users.model import User

router = APIRouter(prefix="/admin/setup-checklist", tags=["setup"])


def _branding(db):
    b = db.query(OrgBranding).first()
    return bool(b and (b.display_name or b.primary_color or b.tagline)) or db.query(OrgLogo).first() is not None


def _people(db):
    return db.query(User).count() > 1 or db.query(Group).first() is not None


# id, title, description, link, areas of which the admin needs at least one, completion test
ITEMS = [
    ("branding", "Set your branding", "Name, colour and logo shown on sign-in and in email.", "/admin/branding", ("branding",), _branding),
    ("people", "Add a user or a group", "Onboard the first person you will give access to.", "/admin/users", ("users", "groups"), _people),
    ("application", "Add an application", "Connect your first app with OpenID Connect or SAML.", "/admin/applications", ("applications",),
     lambda db: db.query(Application).first() is not None),
    ("mfa_policy", "Review the sign-in policy", "Password rules, lockout and session lifetime.", "/admin/security-policy", ("security",),
     lambda db: db.query(OrgSecurityPolicy).first() is not None),
    ("network_zones", "Define a network zone", "Name the office or VPN ranges your policies can refer to.", "/admin/network-zones", ("security",),
     lambda db: db.query(NetworkZone).first() is not None),
]
_IDS = {i[0] for i in ITEMS}


@router.get("")
def checklist(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    dismissed = {d.item for d in db.query(ChecklistDismissal).filter(ChecklistDismissal.user_id == user.id)}
    items = []
    for key, title, description, href, areas, done in ITEMS:
        if not any(permissions.has_access(db, user, a) for a in areas):
            continue  # an area this admin cannot read is not mentioned at all
        items.append({"id": key, "title": title, "description": description, "href": href, "done": bool(done(db)), "dismissed": key in dismissed})
    return {"items": items}


@router.post("/{item}/dismiss", status_code=204)
def dismiss(item: str, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    if item not in _IDS:
        raise HTTPException(status_code=404, detail="Unknown item")
    if not db.query(ChecklistDismissal).filter_by(user_id=user.id, item=item).first():
        db.add(ChecklistDismissal(user_id=user.id, item=item))
        db.commit()


@router.delete("/{item}/dismiss", status_code=204)
def restore(item: str, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    db.query(ChecklistDismissal).filter_by(user_id=user.id, item=item).delete()
    db.commit()
