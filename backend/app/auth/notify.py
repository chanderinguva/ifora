"""Best-effort security notifications by email (IFORA-43): a new device signed in, or a sign-in factor changed.

Never blocks or fails the action it reports: no mail server configured means nothing is sent, and a failure is logged
without the message. The message names the action, the time and the address, and never contains a link or a code.
"""

import threading
from datetime import datetime, timezone

import structlog
from sqlalchemy.orm import Session

from backend.app import mailer

logger = structlog.get_logger(__name__)
SEND_IN_BACKGROUND = True  # tests switch this off so the message is sent before the assertion


def _deliver(msg) -> None:
    try:
        mailer.send(msg, timeout=10)
    except Exception as e:  # noqa: BLE001 - delivery details stay out of the response
        logger.warning("security_mail.send_failed", error=type(e).__name__)


def notify(db: Session, user, what: str, ip: str = "") -> bool:
    """Compose now (cheap, uses the caller's session) and send on a background thread. Returns whether a message was queued."""
    if not mailer.configured() or not user.email:
        return False
    try:
        from backend.app.branding import templates

        subject, body, html, logo = templates.rich_email(
            db, "security_alert", first_name=user.first_name, action=what,
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), ip_address=ip or "unknown")
        msg = mailer.build(user.email, subject, body, html=html, logo=logo)
    except Exception as e:  # noqa: BLE001
        logger.warning("security_mail.compose_failed", error=type(e).__name__)
        return False
    if SEND_IN_BACKGROUND:
        threading.Thread(target=_deliver, args=(msg,), daemon=True).start()
    else:
        _deliver(msg)
    return True
