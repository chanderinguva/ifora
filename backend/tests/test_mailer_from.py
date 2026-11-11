"""The From header: `Name <address>` when SMTP_FROM_NAME is set, the bare address otherwise."""

from email.utils import parseaddr

from backend.app import mailer
from backend.app.config import settings


def test_from_header_has_the_display_name(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_FROM", "noreply@ifora.app")
    monkeypatch.setattr(settings, "SMTP_FROM_NAME", "IFora")
    msg = mailer.build("pat@example.com", "Hi", "body")
    assert msg["From"] == "IFora <noreply@ifora.app>"
    assert parseaddr(msg["From"]) == ("IFora", "noreply@ifora.app")


def test_from_header_is_the_bare_address_without_a_name(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_FROM", "noreply@ifora.app")
    monkeypatch.setattr(settings, "SMTP_FROM_NAME", "  ")
    assert mailer.build("pat@example.com", "Hi", "body")["From"] == "noreply@ifora.app"


def test_from_name_with_specials_is_quoted(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_FROM", "noreply@ifora.app")
    monkeypatch.setattr(settings, "SMTP_FROM_NAME", 'IFora, "Identity"')
    assert parseaddr(mailer.build("pat@example.com", "Hi", "body")["From"]) == ('IFora, "Identity"', "noreply@ifora.app")
