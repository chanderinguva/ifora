"""Outbound email, shared by recipes (send_email step) and the account flows (invite, password reset).

`overrides["send"]` is a test seam. With no SMTP host/sender configured, `configured()` is False and callers must
degrade gracefully (the account flows say so instead of pretending a mail went out).
"""

import smtplib
import ssl
from email.message import EmailMessage
from typing import Any, Dict

from backend.app.config import settings

overrides: Dict[str, Any] = {}


def configured() -> bool:
    return bool((settings.SMTP_HOST and settings.SMTP_FROM) or "send" in overrides)


def send(msg: EmailMessage, timeout: float = 10) -> None:
    """Send one message. Raises smtplib.SMTPException / OSError on failure."""
    if "send" in overrides:
        return overrides["send"](msg)
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=timeout) as smtp:
        if settings.SMTP_STARTTLS:
            smtp.starttls(context=ssl.create_default_context())  # verify the server certificate and hostname
        if settings.SMTP_USERNAME:
            smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        smtp.send_message(msg)


def build(to: str, subject: str, body: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = settings.SMTP_FROM or "noreply@localhost", to, subject
    msg.set_content(body)
    return msg
