"""Tenant-scoped, administrator-editable identity notification templates.

Only explicit, allowlisted {{variables}} are replaced, once. The stored body is
plain text; the separately maintained HTML renderer escapes all displayed values.
"""
import re
from typing import Dict, Optional

from sqlalchemy.orm import Session

from backend.app.branding.models import EmailTemplate, OrgBranding
from backend.app.environment import name as environment_name, subject as environment_subject

DEFAULT_ORG_NAME = "Ifora"
VARIABLES = {
    "first_name": "Recipient's first name",
    "org_name": "Tenant or organization name",
    "link": "One-time secure action link",
    "valid_for": "Expiration window for a link or code",
    "code": "One-time enrollment or verification code",
    "environment": "Demo, development, staging, test, or production",
    "action": "Security event description",
    "timestamp": "Event time, if known",
    "ip_address": "Source IP address, if known",
}
DEFAULTS: Dict[str, dict] = {
    "invite": {
        "label": "Account invitation", "category": "Account", "live": True,
        "required": ("link",), "cta": "Activate account",
        "subject": "You have been invited to {{org_name}}",
        "body": "Hello {{first_name}},\n\nAn administrator created an account for you. Set your password to get started:\n\n{{link}}\n\nThe link works once and expires in {{valid_for}}. If you did not expect this email, ignore it.\n",
    },
    "reset": {
        "label": "Password reset", "category": "Account", "live": True,
        "required": ("link",), "cta": "Reset password",
        "subject": "Reset your {{org_name}} password",
        "body": "Hello {{first_name}},\n\nA password reset was requested for your account. If this was you, use the secure link below:\n\n{{link}}\n\nThe link works once and expires in {{valid_for}}. If you did not request this change, you can ignore this message. Your password will not change.\n",
    },
    "mfa_enrollment": {
        "label": "Authenticator enrollment code", "category": "Security", "live": True,
        "required": ("code",), "cta": "",
        "subject": "Your {{org_name}} enrollment code",
        "body": "Hello {{first_name}},\n\nUse this one-time code to set up your passkey or authenticator app in Account settings > Security:\n\n{{code}}\n\nThe code works once and expires in {{valid_for}}. If you did not request this, ignore it. Do not share the code with anyone.\n",
    },
    "email_verification": {
        "label": "Verify email address", "category": "Account", "live": False,
        "required": ("link",), "cta": "Verify email",
        "subject": "Verify your email for {{org_name}}",
        "body": "Hello {{first_name}},\n\nConfirm your email address by following the secure link:\n\n{{link}}\n\nThis link expires in {{valid_for}}. If you did not request an account, ignore this email.\n",
    },
    "account_unlock": {
        "label": "Unlock account", "category": "Security", "live": False,
        "required": ("link",), "cta": "Unlock account",
        "subject": "Unlock your {{org_name}} account",
        "body": "Hello {{first_name}},\n\nYou can use the secure link below to unlock your account:\n\n{{link}}\n\nThe link expires in {{valid_for}}. If you did not request this, contact your administrator.\n",
    },
    "password_changed": {
        "label": "Password changed", "category": "Security", "live": False,
        "required": (), "cta": "",
        "subject": "Your {{org_name}} password was changed",
        "body": "Hello {{first_name}},\n\nYour account password was changed. If this was you, no action is needed.\n\nIf you did not make this change, contact your administrator immediately.\n",
    },
    "security_alert": {
        "label": "Security activity alert", "category": "Security", "live": False,
        "required": (), "cta": "",
        "subject": "Security activity on your {{org_name}} account",
        "body": "Hello {{first_name}},\n\nA security event was recorded on your account: {{action}}\n\nTime: {{timestamp}}\nIP address: {{ip_address}}\n\nIf this was not you, contact your administrator immediately.\n",
    },
    "account_deactivated": {
        "label": "Account deactivated", "category": "Lifecycle", "live": False,
        "required": (), "cta": "",
        "subject": "Your {{org_name}} account has been deactivated",
        "body": "Hello {{first_name}},\n\nYour access to {{org_name}} has been deactivated. If you believe this is a mistake, contact your organization administrator.\n",
    },
}
KEYS = tuple(DEFAULTS)
MAX_SUBJECT, MAX_BODY = 200, 4000
_TOKEN = re.compile(r"\{\{\s*([a-zA-Z_]+)\s*\}\}")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def validate(subject: str, body: str, key: str = "invite") -> Optional[str]:
    """Validate a draft without executing code or permitting unknown interpolation."""
    if key not in DEFAULTS:
        return "Unknown email template"
    if "\n" in subject or "\r" in subject:
        return "The subject must be a single line"
    if _CTRL.search(subject) or _CTRL.search(body):
        return "Control characters are not allowed"
    unknown = sorted({m for m in _TOKEN.findall(subject + "\n" + body) if m not in VARIABLES})
    if unknown:
        return "Unknown variable(s): " + ", ".join("{{" + u + "}}" for u in unknown)
    if "{{" in _TOKEN.sub("", subject + "\n" + body):
        return "A '{{' is not part of a valid {{variable}}"
    for required in DEFAULTS[key]["required"]:
        if required not in _TOKEN.findall(body):
            return "The body must contain {{" + required + "}}, otherwise the recipient cannot use the email"
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


def values(db: Session, *, first_name: str = "", link: str = "", valid_for: str = "",
           code: str = "", action: str = "", timestamp: str = "", ip_address: str = "") -> dict:
    return {"first_name": first_name or "", "org_name": org_name(db), "link": link,
            "valid_for": valid_for, "code": code, "action": action,
            "timestamp": timestamp, "ip_address": ip_address, "environment": environment_name()}


def compose(db: Session, key: str, *, first_name: str, link: str = "", valid_for: str = "",
            code: str = "", action: str = "", timestamp: str = "", ip_address: str = "") -> tuple:
    """Return (subject, plain body); invalid legacy overrides fall back to defaults."""
    t = current(db, key)
    if t["customised"] and validate(t["subject"], t["body"], key):
        t = {**DEFAULTS[key], "customised": False}
    vals = values(db, first_name=first_name, link=link, valid_for=valid_for, code=code,
                  action=action, timestamp=timestamp, ip_address=ip_address)
    subject = render(t["subject"], vals)
    subject = re.sub(r"[\r\n]+", " ", subject).strip()[:MAX_SUBJECT - 12]
    return environment_subject(subject), render(t["body"], vals)


def rich_email(db: Session, key: str, *, first_name: str, link: str = "", valid_for: str = "",
               code: str = "", **kwargs):
    """Build a standards-based multipart message payload for the existing SMTP sender."""
    from backend.app.branding import email_html
    subject, body = compose(db, key, first_name=first_name, link=link,
                            valid_for=valid_for, code=code, **kwargs)
    html = email_html.render(db, title=DEFAULTS[key]["label"], body=body,
                             link=link, code=code, action_label=DEFAULTS[key]["cta"])
    return subject, body, html, email_html.logo_attachment(db)
