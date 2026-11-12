"""Startup guards (IFORA-49 / SEC-A-5): an unsafe production configuration refuses to boot; development is untouched."""

import logging

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend.app import config_guards
from backend.app.api import create_app
from backend.app.config import settings

GOOD_SECRET = "Zq8vN3pL0xW5mK2cR7tY9uB4eH1gJ6sD8fA3nQ5wE2rT7y"
GOOD_ADMIN_SECRET = "Hk4bV9cX1zM6nL3qP8wR2tY5uE7iO0aS4dF6gJ9kL1mN3b"


def make_production_valid(monkeypatch):
    """A configuration the guards accept; tests then break one thing at a time."""
    for name, value in {
        "ENVIRONMENT": "production",
        "SESSION_COOKIE_SECURE": True,
        "SECRET_KEY": GOOD_SECRET,
        "ADMIN_SECRET_KEY": GOOD_ADMIN_SECRET,
        "MFA_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "OIDC_KEY_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "CORS_ORIGINS": ["https://id.example.com"],
        "DEBUG": False,
        "PUBLIC_APP_URL": "https://id.example.com",
        "OIDC_ISSUER": "https://id.example.com",
    }.items():
        monkeypatch.setattr(settings, name, value)


def problems_naming(setting, monkeypatch=None):
    return [p for p in config_guards.validate_settings(settings) if setting in p]


def test_valid_production_config_is_accepted(monkeypatch):
    make_production_valid(monkeypatch)
    assert config_guards.validate_settings(settings) == []
    assert create_app().openapi_url is None  # and docs stay hidden


def test_prod_requires_secure_cookie(monkeypatch):
    make_production_valid(monkeypatch)
    monkeypatch.setattr(settings, "SESSION_COOKIE_SECURE", False)
    with pytest.raises(RuntimeError, match="SESSION_COOKIE_SECURE"):
        create_app()


@pytest.mark.parametrize("name", ["SECRET_KEY", "ADMIN_SECRET_KEY"])
@pytest.mark.parametrize("bad", ["", "short", "a" * 40, "change-me-change-me-change-me-change-me-1234", "mysecretmysecretmysecretmysecret12345"])
def test_prod_rejects_default_or_weak_secrets(monkeypatch, name, bad):
    make_production_valid(monkeypatch)
    monkeypatch.setattr(settings, name, bad)
    with pytest.raises(RuntimeError, match=name):
        create_app()


def test_prod_rejects_identical_session_and_admin_secrets(monkeypatch):
    make_production_valid(monkeypatch)
    monkeypatch.setattr(settings, "ADMIN_SECRET_KEY", GOOD_SECRET)
    assert problems_naming("must be different")


def test_prod_requires_a_separate_oidc_key_encryption_key(monkeypatch):
    make_production_valid(monkeypatch)
    monkeypatch.setattr(settings, "OIDC_KEY_ENCRYPTION_KEY", "")
    assert problems_naming("OIDC_KEY_ENCRYPTION_KEY")
    monkeypatch.setattr(settings, "OIDC_KEY_ENCRYPTION_KEY", settings.MFA_ENCRYPTION_KEY)
    assert problems_naming("must differ")


def test_prod_rejects_wildcard_cors(monkeypatch):
    make_production_valid(monkeypatch)
    monkeypatch.setattr(settings, "CORS_ORIGINS", ["https://id.example.com", "*"])
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        create_app()


def test_prod_rejects_debug_and_plain_http_urls(monkeypatch):
    make_production_valid(monkeypatch)
    monkeypatch.setattr(settings, "DEBUG", True)
    monkeypatch.setattr(settings, "PUBLIC_APP_URL", "http://id.example.com")
    monkeypatch.setattr(settings, "OIDC_ISSUER", "http://id.example.com")
    names = " ".join(config_guards.validate_settings(settings))
    assert "DEBUG" in names and "PUBLIC_APP_URL" in names and "OIDC_ISSUER" in names


def test_dev_defaults_unchanged(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "SESSION_COOKIE_SECURE", False)
    monkeypatch.setattr(settings, "SECRET_KEY", "x" * 40)
    monkeypatch.setattr(settings, "OIDC_KEY_ENCRYPTION_KEY", "")
    assert config_guards.validate_settings(settings) == []
    assert create_app().openapi_url == "/openapi.json"


def test_guard_message_never_contains_a_secret(monkeypatch):
    make_production_valid(monkeypatch)
    leaked = "TopSecretValue-ShouldNeverAppear-0123456789abcdef"
    monkeypatch.setattr(settings, "SECRET_KEY", leaked)           # contains a placeholder word -> rejected
    monkeypatch.setattr(settings, "SESSION_COOKIE_SECURE", False)
    with pytest.raises(RuntimeError) as e:
        create_app()
    msg = str(e.value)
    assert "SECRET_KEY" in msg and leaked not in msg
    assert settings.ADMIN_SECRET_KEY not in msg and settings.MFA_ENCRYPTION_KEY not in msg


def test_forwarded_ips_default_detection():
    assert config_guards.forwarded_ips_is_default({}) is True
    assert config_guards.forwarded_ips_is_default({"FORWARDED_ALLOW_IPS": "127.0.0.1"}) is True
    assert config_guards.forwarded_ips_is_default({"FORWARDED_ALLOW_IPS": "10.0.0.5"}) is False


def test_forwarded_header_untrusted_by_default_is_reported_once(monkeypatch, caplog):
    make_production_valid(monkeypatch)
    monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
    client = TestClient(create_app())
    with caplog.at_level(logging.ERROR):
        client.get("/health", headers={"X-Forwarded-For": "203.0.113.9"})
        client.get("/health", headers={"X-Forwarded-For": "203.0.113.9"})
    warned = [r for r in caplog.records if "FORWARDED_ALLOW_IPS" in r.getMessage()]
    assert len(warned) == 1


def test_no_forwarded_warning_when_trusted_proxy_is_configured(monkeypatch, caplog):
    make_production_valid(monkeypatch)
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "10.0.0.5")
    client = TestClient(create_app())
    with caplog.at_level(logging.ERROR):
        client.get("/health", headers={"X-Forwarded-For": "203.0.113.9"})
    assert not [r for r in caplog.records if "FORWARDED_ALLOW_IPS" in r.getMessage()]


def test_demo_retains_public_deployment_hardening(monkeypatch):
    make_production_valid(monkeypatch)
    monkeypatch.setattr(settings, "ENVIRONMENT", "demo")
    assert config_guards.validate_settings(settings) == []
    assert create_app().openapi_url is None
    monkeypatch.setattr(settings, "SESSION_COOKIE_SECURE", False)
    assert problems_naming("SESSION_COOKIE_SECURE")
