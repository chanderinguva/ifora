"""Cloudflare Access allowlist kept in step with users; SMTP over implicit TLS."""

import copy
import smtplib

import pytest

from backend.app import mailer
from backend.app import config_guards
from backend.app.auth import access_allowlist
from backend.app.config import settings
from backend.app.users.model import User
from tests.conftest import make_user
from tests.test_config_guards import make_production_valid

POLICY = {"id": "p1", "name": "Invited friends", "decision": "allow", "precedence": 1, "session_duration": "24h",
          "include": [{"email": {"email": "keep@example.com"}}], "exclude": [], "require": [], "created_at": "x"}


@pytest.fixture
def cf(monkeypatch):
    """A fake Cloudflare policy endpoint. `state['policy']` is the stored policy; `state['calls']` the traffic."""
    state = {"policy": copy.deepcopy(POLICY), "calls": [], "fail": False}

    def fake(method, body=None):
        state["calls"].append((method, body))
        if state["fail"]:
            raise RuntimeError("cloudflare down")
        if method == "PUT":
            state["policy"] = {**state["policy"], **body}
        return copy.deepcopy(state["policy"])

    for name, value in {"ACCESS_ALLOWLIST_TOKEN": "tok", "ACCESS_ALLOWLIST_ACCOUNT_ID": "acc",
                        "ACCESS_ALLOWLIST_APP_ID": "app", "ACCESS_ALLOWLIST_POLICY_ID": "p1"}.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(access_allowlist, "_request", fake)
    return state


def emails(state):
    return [r["email"]["email"] for r in state["policy"]["include"]]


def puts(state):
    return [c for c in state["calls"] if c[0] == "PUT"]


# --- service ------------------------------------------------------------------------------------------------

def test_disabled_when_not_configured_makes_no_calls(monkeypatch):
    monkeypatch.setattr(access_allowlist, "_request", lambda *a, **k: pytest.fail("must not call Cloudflare"))
    assert access_allowlist.add("x@example.com") == "disabled"
    assert access_allowlist.remove("x@example.com") == "disabled"


def test_add_appends_and_keeps_the_rest_of_the_policy(cf):
    assert access_allowlist.add("New.Friend@Example.com") == "added"
    assert emails(cf) == ["keep@example.com", "new.friend@example.com"]
    body = puts(cf)[0][1]
    assert body["name"] == "Invited friends" and body["decision"] == "allow" and body["session_duration"] == "24h"
    assert "id" not in body and "created_at" not in body  # only fields the API accepts are sent back


def test_add_is_idempotent_and_case_insensitive(cf):
    assert access_allowlist.add("KEEP@example.com") == "already"
    assert puts(cf) == []


def test_remove_drops_only_that_email(cf):
    access_allowlist.add("a@example.com")
    assert access_allowlist.remove("A@example.com") == "removed"
    assert emails(cf) == ["keep@example.com"]
    assert access_allowlist.remove("a@example.com") == "absent"


def test_remove_refuses_protected_addresses(cf):
    assert access_allowlist.remove("keep@example.com", keep=("Keep@Example.com",)) == "kept"
    assert emails(cf) == ["keep@example.com"] and cf["calls"] == []


def test_failures_never_raise(cf):
    cf["fail"] = True
    assert access_allowlist.add("x@example.com") == "failed"
    assert access_allowlist.remove("x@example.com") == "failed"


def test_partial_configuration_is_not_enabled(monkeypatch):
    monkeypatch.setattr(settings, "ACCESS_ALLOWLIST_TOKEN", "tok")
    assert not access_allowlist.enabled()


def test_token_is_never_logged(cf, capsys):
    cf["fail"] = True
    access_allowlist.add("x@example.com")
    out = capsys.readouterr()
    assert "tok" not in (out.out + out.err).replace("token", "")


# --- through the user routes ---------------------------------------------------------------------------------

def test_creating_a_user_adds_them_to_the_allowlist(cf, super_admin):
    r = super_admin.post("/admin/users", {"first_name": "A", "last_name": "B", "email": "invitee@example.com", "generate_password": True})
    assert r.status_code == 201, r.text
    assert r.json()["access_allowlist"] == "added" and "invitee@example.com" in emails(cf)


def test_user_is_created_even_if_cloudflare_is_down(cf, super_admin, db):
    cf["fail"] = True
    r = super_admin.post("/admin/users", {"first_name": "A", "last_name": "B", "email": "invitee@example.com", "generate_password": True})
    assert r.status_code == 201 and r.json()["access_allowlist"] == "failed"
    assert db.query(User).filter(User.email == "invitee@example.com").count() == 1


def test_response_has_no_allowlist_field_when_disabled(super_admin):
    r = super_admin.post("/admin/users", {"first_name": "A", "last_name": "B", "email": "invitee@example.com", "generate_password": True})
    assert r.status_code == 201 and "access_allowlist" not in r.json()


def test_invited_user_is_allowlisted_before_the_email_is_sent(cf, super_admin):
    seen = []
    mailer.overrides["send"] = lambda msg: seen.append((msg["To"], "invitee@example.com" in emails(cf)))
    try:
        r = super_admin.post("/admin/users", {"first_name": "A", "last_name": "B", "email": "invitee@example.com", "send_invite": True})
    finally:
        mailer.overrides.pop("send", None)
    assert r.status_code == 201 and r.json()["invitation_sent"] is True
    assert seen == [("invitee@example.com", True)]


def test_invited_user_is_not_an_administrator(cf, super_admin, db):
    super_admin.post("/admin/users", {"first_name": "A", "last_name": "B", "email": "invitee@example.com", "generate_password": True})
    u = db.query(User).filter(User.email == "invitee@example.com").one()
    assert (u.is_admin, u.is_super_admin) == (False, False)


def test_deleting_a_user_removes_them_from_the_allowlist(cf, super_admin, db):
    uid = super_admin.post("/admin/users", {"first_name": "A", "last_name": "B", "email": "invitee@example.com", "generate_password": True}).json()["id"]
    assert super_admin.delete(f"/admin/users/{uid}").status_code == 200
    assert "invitee@example.com" not in emails(cf) and "keep@example.com" in emails(cf)


def test_delete_succeeds_even_if_cloudflare_is_down(cf, super_admin, db):
    uid = super_admin.post("/admin/users", {"first_name": "A", "last_name": "B", "email": "invitee@example.com", "generate_password": True}).json()["id"]
    cf["fail"] = True
    assert super_admin.delete(f"/admin/users/{uid}").status_code == 200
    assert db.query(User).filter(User.email == "invitee@example.com").count() == 0


# --- configuration -------------------------------------------------------------------------------------------

def test_production_requires_all_or_none_of_the_allowlist_settings(monkeypatch):
    make_production_valid(monkeypatch)
    assert config_guards.validate_settings(settings) == []
    monkeypatch.setattr(settings, "ACCESS_ALLOWLIST_TOKEN", "tok")
    assert any("ACCESS_ALLOWLIST" in p for p in config_guards.validate_settings(settings))


# --- SMTP over implicit TLS ----------------------------------------------------------------------------------

class FakeConn:
    def __init__(self, kind, log, *a, **k):
        self.kind, self.log = kind, log
        log.append((kind, a, k.get("context") is not None))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, **k):
        self.log.append(("starttls",))

    def login(self, u, p):
        self.log.append(("login", u))

    def send_message(self, msg):
        self.log.append(("sent", msg["To"]))


def test_implicit_tls_uses_smtp_ssl_and_never_starttls(monkeypatch):
    log = []
    monkeypatch.setattr(smtplib, "SMTP_SSL", lambda *a, **k: FakeConn("ssl", log, *a, **k))
    monkeypatch.setattr(smtplib, "SMTP", lambda *a, **k: pytest.fail("plain SMTP must not be used"))
    for name, value in {"SMTP_HOST": "smtp.mx.cloudflare.net", "SMTP_PORT": 465, "SMTP_FROM": "noreply@example.com",
                        "SMTP_USERNAME": "api_token", "SMTP_PASSWORD": "x", "SMTP_IMPLICIT_TLS": True, "SMTP_STARTTLS": True}.items():
        monkeypatch.setattr(settings, name, value)
    mailer.send(mailer.build("to@example.com", "s", "b"))
    assert log[0] == ("ssl", ("smtp.mx.cloudflare.net", 465), True)  # certificate verification context supplied
    assert ("starttls",) not in log and ("login", "api_token") in log and ("sent", "to@example.com") in log


def test_default_still_uses_starttls(monkeypatch):
    log = []
    monkeypatch.setattr(smtplib, "SMTP", lambda *a, **k: FakeConn("plain", log, *a, **k))
    for name, value in {"SMTP_HOST": "smtp.example.com", "SMTP_PORT": 587, "SMTP_FROM": "noreply@example.com",
                        "SMTP_USERNAME": "", "SMTP_IMPLICIT_TLS": False, "SMTP_STARTTLS": True}.items():
        monkeypatch.setattr(settings, name, value)
    mailer.send(mailer.build("to@example.com", "s", "b"))
    assert ("starttls",) in log
