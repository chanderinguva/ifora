"""Email templates: built-in defaults, a deliberately dumb renderer, and the rules for administrator edits.

The renderer substitutes `{{name}}` for a fixed set of variables, once, with no expressions, no loops and no recursion, so a
template (or a user's first name) can never execute anything or pull in another value. Emails are plain text; nothing is
HTML-escaped because nothing is interpreted as HTML.
"""

import re
from typing import Dict, Optional

from sqlalchemy.orm import Session

from backend.app.branding.models import EmailTemplate, OrgBranding

DEFAULT_ORG_NAME = "Ifora"
VARIABLES = {
    "first_name": "The recipient's first name",
    "org_name": "Your organization's display name",
    "link": "The one-time link (required)",
    "valid_for": "How long the link works, for example '24 hours'",
}
DEFAULTS: Dict[str, dict] = {
    "invite": {
        "label": "Invitation",
        "subject": "You have been invited to {{org_name}}",
        "body": "Hello {{first_name}},\n\nAn administrator created an account for you. Set your password to get started:\n\n{{link}}\n\nThe link works once and expires in {{valid_for}}. If you did not expect this email, ignore it.\n",
    },
    "reset": {
        "label": "Password reset",
        "subject": "Reset your {{org_name}} password",
        "body": "Hello {{first_name}},\n\nSomeone (hopefully you) asked to reset your password. Choose a new one here:\n\n{{link}}\n\nThe link works once and expires in {{valid_for}}. If you did not expect this email, ignore it.\n",
    },
}
KEYS = tuple(DEFAULTS)
MAX_SUBJECT, MAX_BODY = 200, 4000
_TOKEN = re.compile(r"\{\{\s*([a-zA-Z_]+)\s*\}\}")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def validate(subject: str, body: str) -> Optional[str]:
    """Return a human-readable problem with an edited template, or None."""
    if "\n" in subject or "\r" in subject:
        return "The subject must be a single line"
    if _CTRL.search(subject) or _CTRL.search(body):
        return "Control characters are not allowed"
    unknown = sorted({m for m in _TOKEN.findall(subject + "\n" + body) if m not in VARIABLES})
    if unknown:
        return "Unknown variable(s): " + ", ".join("{{" + u + "}}" for u in unknown)
    if "{{" in _TOKEN.sub("", subject + "\n" + body):
        return "A '{{' is not part of a valid {{variable}}"
    if not any(m == "link" for m in _TOKEN.findall(body)):
        return "The body must contain {{link}}, otherwise the recipient cannot use the email"
    return None


def render(text: str, values: Dict[str, str]) -> str:
    return _TOKEN.sub(lambda m: values.get(m.group(1), ""), text)


def org_name(db: Session) -> str:
    b = db.query(OrgBranding).first()
    return (b.display_name if b and b.display_name else DEFAULT_ORG_NAME)


def current(db: Session, key: str) -> dict:
    row = db.query(EmailTemplate).filter(EmailTemplate.key == key).first()
    d = DEFAULTS[key]
    return {"subject": row.subject if row else d["subject"], "body": row.body if row else d["body"], "customised": row is not None}


def compose(db: Session, key: str, *, first_name: str, link: str, valid_for: str) -> tuple:
    """(subject, body) for a real send. A stored template that fails today's validation falls back to the built-in text."""
    t = current(db, key)
    if t["customised"] and validate(t["subject"], t["body"]):
        t = {**DEFAULTS[key], "customised": False}
    vals = {"first_name": first_name or "", "org_name": org_name(db), "link": link, "valid_for": valid_for}
    subject = render(t["subject"], vals)
    return re.sub(r"[\r\n]+", " ", subject).strip()[:MAX_SUBJECT], render(t["body"], vals)
