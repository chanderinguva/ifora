"""Fixes from the independent security review: audit data stays with the reports role, new admins start least-privileged,
system groups keep their membership, SMTP verifies certificates, production refuses an insecure cookie setup."""

import ssl
from unittest import mock

import pytest

from backend.app import mailer
from backend.app.config import settings
from tests.conftest import make_user
from tests.test_admin_roles import give


def test_help_desk_gets_counts_but_not_the_system_log(super_admin, admin):
    give(super_admin, admin, "help_desk_admin")
    s = admin.get("/admin/stats").json()
    assert s["users_total"] >= 1 and s["recent_events"] == []
    assert super_admin.get("/admin/stats").json()["recent_events"]


def test_report_admin_still_sees_recent_events(super_admin, admin):
    give(super_admin, admin, "report_admin")
    assert admin.get("/admin/stats").json()["recent_events"]


def test_user_events_need_the_reports_area(db, super_admin, admin):
    u = make_user(db, "someone@example.com")
    give(super_admin, admin, "help_desk_admin")
    assert admin.get(f"/admin/users/{u.id}/events").status_code == 403
    give(super_admin, admin, "report_admin")
    assert admin.get(f"/admin/users/{u.id}/events").status_code == 200


def test_search_only_returns_what_the_role_may_see(db, super_admin, admin):
    make_user(db, "findme.user@example.com")
    assert super_admin.post("/admin/groups", {"name": "findme group"}).status_code in (200, 201)
    give(super_admin, admin, "report_admin")  # users read, no groups/applications/automation
    kinds = {r["kind"] for r in admin.get("/admin/search?q=findme").json()["results"]}
    assert kinds == {"user"}


def test_promoted_admin_starts_read_only(db, super_admin):
    u = make_user(db, "future.admin@example.com")
    assert super_admin.patch(f"/admin/users/{u.id}", {"is_admin": True}).status_code == 200
    assert super_admin.get(f"/admin/roles/users/{u.id}").json()["roles"] == ["read_only_admin"]


def test_created_admin_starts_read_only(super_admin):
    r = super_admin.post("/admin/users", {"email": "new.admin@example.com", "first_name": "N", "last_name": "A",
                                          "generate_password": True, "is_admin": True})
    assert r.status_code == 201, r.text
    uid = r.json()["user"]["id"] if "user" in r.json() else r.json()["id"]
    assert super_admin.get(f"/admin/roles/users/{uid}").json()["roles"] == ["read_only_admin"]


def test_system_group_membership_cannot_be_edited(db, super_admin):
    from backend.app.groups.model import Group

    g = Group(name="Everyone-ish", description="", is_system_group=True)
    db.add(g)
    db.commit()
    u = make_user(db, "member.x@example.com")
    assert super_admin.post(f"/admin/groups/{g.id}/members", {"user_id": u.id}).status_code == 403
    assert super_admin.delete(f"/admin/groups/{g.id}/members/{u.id}").status_code == 403


def test_starttls_verifies_the_certificate(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", "mail.example.com")
    monkeypatch.setattr(settings, "SMTP_STARTTLS", True)
    monkeypatch.setattr(settings, "SMTP_USERNAME", "")
    with mock.patch("smtplib.SMTP") as smtp:
        mailer.send(mailer.build("a@example.com", "s", "b"))
    ctx = smtp.return_value.__enter__.return_value.starttls.call_args.kwargs["context"]
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname


def test_production_requires_secure_cookies_and_hides_docs(monkeypatch):
    from backend.app.api import create_app
    from tests.test_config_guards import make_production_valid

    make_production_valid(monkeypatch)   # a full valid production config; only the cookie flag differs below
    monkeypatch.setattr(settings, "SESSION_COOKIE_SECURE", False)
    with pytest.raises(RuntimeError):
        create_app()
    monkeypatch.setattr(settings, "SESSION_COOKIE_SECURE", True)
    assert create_app().openapi_url is None


def test_api_sets_basic_security_headers(anon):
    r = anon.get("/me")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["referrer-policy"] == "no-referrer"
