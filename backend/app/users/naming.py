"""Standard names for new accounts: username `first.last`, primary email `<username>@PRIMARY_EMAIL_DOMAIN`.

Convention (the same one Okta, Google Workspace and Microsoft 365 default to):
  - lower case, accents folded to ASCII (José -> jose, Müller -> muller), only a-z 0-9 kept inside a name,
    so O'Brien -> obrien and Mary Ann -> maryann; the two names are joined with a dot;
  - a name with no Latin letters (e.g. 李伟) falls back to "user";
  - on a clash the next free number is appended to the whole name: john.smith, john.smith2, john.smith3 ...
    (case-insensitive; the email must be free as well);
  - a handful of role-like names (admin, root, postmaster ...) are never handed out.

The username is assigned once and never changes (see the guard on User.username); the email may. Downstream systems and
SCIM clients should key on the opaque `public_id` (SCIM `id`, OIDC `sub`) or the IdP's `externalId`, never on the email.
"""

import re
import unicodedata
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.users.model import User

MAX_BASE = 44            # leaves room for a numeric suffix inside the 50-character username limit
MAX_SUFFIX = 9999
RESERVED = frozenset({
    "admin", "administrator", "root", "system", "support", "security", "postmaster", "hostmaster", "webmaster",
    "abuse", "noreply", "no-reply", "info", "mail", "null", "undefined", "user", "test", "api", "www", "ftp",
})
_TRANSLIT = str.maketrans({"ß": "ss", "ø": "o", "æ": "ae", "œ": "oe", "đ": "d", "ð": "d", "þ": "th", "ł": "l", "ı": "i"})


def fold(name: str) -> str:
    """One name part, reduced to [a-z0-9]."""
    s = unicodedata.normalize("NFKD", (name or "").lower().translate(_TRANSLIT))
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in s if not unicodedata.combining(c)))


def base_username(first: str, last: str) -> str:
    parts = [p for p in (fold(first), fold(last)) if p]
    base = ".".join(parts) if parts else "user"
    base = base[:MAX_BASE].rstrip(".")
    return base if len(base) >= 2 else base + "0"


def email_for(username: str) -> Optional[str]:
    return f"{username}@{settings.PRIMARY_EMAIL_DOMAIN}" if settings.PRIMARY_EMAIL_DOMAIN else None


def is_free(db: Session, username: str) -> bool:
    """Free = no user has this username (any status) and none has the email it would get."""
    if username in RESERVED:
        return False
    if db.query(User.id).filter(func.lower(User.username) == username).first():
        return False
    email = email_for(username)
    return not (email and db.query(User.id).filter(func.lower(User.email) == email).first())


def generate_username(db: Session, first: str, last: str, skip: int = 0) -> str:
    """The first free name in base, base2, base3 ... `skip` lets a caller that lost a race move on."""
    base = base_username(first, last)
    n = 1 + skip
    while n <= MAX_SUFFIX:
        candidate = base if n == 1 else f"{base}{n}"
        if is_free(db, candidate):
            return candidate
        n += 1
    raise ValueError("No free username for this name")
