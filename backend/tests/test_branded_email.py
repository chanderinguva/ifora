"""Transactional identity email rendering, environment identity, and safe previews."""

import pytest

from backend.app import mailer
from backend.app.branding import templates as T
from backend.app.config import settings
from backend.app.environment import name, subject


@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setitem(mailer.overrides, "send", sent.append)
    from backend.app import ratelimit
    monkeypatch.setattr(ratelimit, "check", lambda *a, **kw: None)
    monkeypatch.setattr(ratelimit, "hit", lambda *a, **kw: None)
    return sent


@pytest.mark.parametrize("raw,expected,prefix", [
    ("demo", "demo", "[DEMO] "),
    ("development", "development", "[DEV] "),
    ("staging", "staging", "[STAGING] "),
    ("test", "test", "[TEST] "),
    ("production", "production", ""),
    ("unexpected", "development", "[DEV] "),
])
def test_environment_identity(monkeypatch, raw, expected, prefix):
    monkeypatch.setattr(settings, "ENVIRONMENT", raw)
    assert name() == expected
    assert subject("Reset password") == prefix + "Reset password"


def test_preview_and_live_messages_use_matching_branding(admin, outbox):
    admin.put("/admin/branding", {"display_name": "Example tenant", "primary_color": "#4f46e5"})
    draft = {"subject": "Join {{org_name}}", "body": "Hello {{first_name}}\n\n{{link}}"}
    preview = admin.post("/admin/email-templates/invite/preview", draft)
    assert preview.status_code == 200
    doc = preview.json()
    assert "<table" in doc["html"] and "Example tenant" in doc["html"]
    assert "data:image/png;base64," in doc["html"]
    assert "TEST ENVIRONMENT" in doc["html"]
    assert "[TEST]" in doc["subject"]
    sent = admin.post("/admin/email-templates/invite/send-test", draft)
    assert sent.status_code == 200
    msg = outbox[-1]
    plain = msg.get_body(preferencelist=("plain",))
    html = msg.get_body(preferencelist=("html",))
    assert plain is not None and html is not None
    assert "Hello" in plain.get_content()
    assert 'cid:ifora-identity-logo' in html.get_content()
    assert 'TEST ENVIRONMENT' in html.get_content()
    assert msg.get_content_type() == "multipart/alternative"
    logos = [part for part in msg.walk() if part.get("Content-ID") == "<ifora-identity-logo>"]
    assert len(logos) == 1
    assert logos[0].get_content_type() == "image/png"
    assert logos[0].get_content_disposition() == "inline"
    assert logos[0].get_payload(decode=True).startswith(b"\x89PNG\r\n\x1a\n")



def test_custom_html_is_escaped_and_not_executable(db, admin):
    admin.put("/admin/branding", {"display_name": "<script>alert(1)</script>"})
    # Braces are rejected in subjects and bodies unless they are known template variables.
    draft = {"subject": "Hello", "body": "<img src=x onerror=alert(1)> {{link}}"}
    response = admin.post("/admin/email-templates/invite/preview", draft)
    assert response.status_code == 200
    assert "&lt;img src=x onerror=alert(1)&gt;" in response.json()["html"]
    assert "<img src=x onerror=alert(1)>" not in response.json()["html"]
    assert "&lt;script&gt;" in response.json()["html"]


def test_new_catalog_does_not_claim_unwired_events(admin):
    items = {entry["key"]: entry for entry in admin.get("/admin/email-templates").json()["items"]}
    assert items["invite"]["live"]
    assert items["reset"]["live"]
    assert items["mfa_enrollment"]["live"]
    assert items["security_alert"]["live"]  # IFORA-43: new-device and factor-change notices
    for key in ("email_verification", "account_unlock", "password_changed", "account_deactivated"):
        assert not items[key]["live"]
    assert "code" in items["mfa_enrollment"]["required"]
    assert T.validate("Hi", "No {{code}}", "mfa_enrollment") is None
    assert "{{code}}" in T.validate("Hi", "No code", "mfa_enrollment")


def test_production_identity_mail_has_no_demo_branding(db, admin, monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    subj, plain, rich, logo = T.rich_email(db, "reset", first_name="Alex", link="https://example.com/reset", valid_for="30 minutes")
    assert subj == "Reset your Ifora password"
    assert "ENVIRONMENT — Not production" not in rich
    assert "Production" in rich
    msg = mailer.build("alex@example.com", subj, plain, html=rich, logo=logo)
    assert msg.get_body(preferencelist=("plain",)) is not None


def test_explicit_non_production_makes_every_notification_obvious(db, admin, monkeypatch):
    for env, display in (("demo", "DEMO"), ("development", "DEV")):
        monkeypatch.setattr(settings, "ENVIRONMENT", env)
        subj, body, rich, _ = T.rich_email(db, "invite", first_name="Alex", link="https://example.com/invite", valid_for="72 hours")
        assert subj.startswith(f"[{display}] ")
        assert f"{display} ENVIRONMENT" in rich
