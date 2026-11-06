"""Claims released to relying parties, by granted scope. One builder serves the ID token and UserInfo so the two
can never disagree. Nothing is released that the scope does not cover."""

from typing import Any, Dict, List

from sqlalchemy.orm import Session

from backend.app.users.model import User


def user_claims(db: Session, user: User, scopes: List[str]) -> Dict[str, Any]:
    c: Dict[str, Any] = {"sub": user.public_id}
    attrs = user.get_profile_attributes()
    if "profile" in scopes:
        c.update(name=user.name, given_name=user.first_name, family_name=user.last_name, preferred_username=user.username)
        if isinstance(attrs.get("timezone"), str) and attrs["timezone"]:
            c["zoneinfo"] = attrs["timezone"]
        if isinstance(attrs.get("locale"), str) and attrs["locale"]:
            c["locale"] = attrs["locale"]
        if user.updated_at:
            c["updated_at"] = int(user.updated_at.timestamp())
    if "email" in scopes:
        c["email"] = user.email  # email_verified is deliberately absent: we do not verify addresses yet
    if "groups" in scopes:
        c["groups"] = sorted(g.name for g in user.groups)
    return c
