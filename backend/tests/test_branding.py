"""Branding and email templates (ADR 015)."""

import base64
import re

import pytest

from backend.app import mailer, ratelimit
from backend.app.branding import templates as T
from tests.conftest import Api, make_user

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64).decode()
SVG = base64.b64encode(b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>").decode()


@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setitem(mailer.overrides, "send", sent.append)
    monkeypatch.setattr(ratelimit, "check", lambda *a, **k: None)
    monkeypatch.setattr(ratelimit, "hit", lambda *a, **k: None)
    return sent


# ---- branding --------------------------------------------------------------------------------------------------------

def test_public_branding_defaults_need_no_sign_in(anon):
    r = anon.get("/branding")
    assert r.status_code == 200
    assert r.json() == {"display_name": "IdentityForge", "custom_name": False, "primary_color": None, "tagline": None, "has_logo": False, "logo_rev": None}
    assert anon.get("/branding/logo").status_code == 404


def test_branding_is_validated_saved_public_and_audited(admin, anon):
    for bad in ({"primary_color": "red"}, {"primary_color": "#12345"}, {"primary_color": "#12345g"}, {"primary_color": "javascript:alert(1)"},
                {"display_name": "A\nB"}, {"display_name": "x" * 61}, {"tagline": "ok\x00no"}):
        assert admin.put("/admin/branding", bad).status_code == 422, bad
    ok = admin.put("/admin/branding", {"display_name": "  Acme Corp ", "primary_color": "#1A73E8", "tagline": "Sign in to Acme"})
    assert ok.status_code == 200 and ok.json()["display_name"] == "Acme Corp" and ok.json()["primary_color"] == "#1a73e8"
    pub = anon.get("/branding").json()
    assert pub["display_name"] == "Acme Corp" and pub["custom_name"] is True and pub["tagline"] == "Sign in to Acme"
    assert any(e["action"] == "BRANDING_UPDATED" for e in admin.get("/admin/audit").json()["items"])
    assert admin.put("/admin/branding", {}).json()["display_name"] == "IdentityForge"     # clearing returns to the default


def test_logo_accepts_only_validated_raster_images(admin, anon):
    assert admin.put("/admin/branding/logo", {"data": SVG}).status_code == 422            # no SVG: it can carry script
    assert admin.put("/admin/branding/logo", {"data": "!!notbase64!!"}).status_code == 422
    assert admin.put("/admin/branding/logo", {"data": base64.b64encode(b"GIF89a" + b"0" * 50).decode()}).status_code == 422
    big = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * (201 * 1024)).decode()
    assert admin.put("/admin/branding/logo", {"data": big}).status_code == 422
    r = admin.put("/admin/branding/logo", {"data": PNG})
    assert r.status_code == 200 and r.json()["has_logo"] is True and r.json()["logo_rev"]
    img = anon.get("/branding/logo")
    assert img.status_code == 200 and img.headers["content-type"] == "image/png" and img.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in img.headers["content-security-policy"]
    assert admin.delete("/admin/branding/logo").json()["has_logo"] is False
    assert anon.get("/branding/logo").status_code == 404


def test_only_permitted_admins_edit_branding(member, anon, super_admin, admin):
    assert member.put("/admin/branding", {"display_name": "x"}).status_code == 403
    assert anon.put("/admin/branding", {"display_name": "x"}, csrf=False).status_code in (401, 403)
    for role, can_write in (("read_only_admin", False), ("help_desk_admin", False), ("report_admin", False), ("org_admin", True)):
        assert super_admin.put(f"/admin/roles/users/{admin.user.id}", {"roles": [role]}).status_code == 200
        assert admin.put("/admin/branding", {"display_name": "Roles"}).status_code == (200 if can_write else 403), role
    assert super_admin.put(f"/admin/roles/users/{admin.user.id}", {"roles": ["read_only_admin"]}).status_code == 200
    assert admin.get("/admin/branding").status_code == 200 and admin.get("/admin/email-templates").status_code == 200


# ---- email templates -------------------------------------------------------------------------------------------------

def test_templates_list_with_defaults_and_variables(admin):
    r = admin.get("/admin/email-templates").json()
    assert {i["key"] for i in r["items"]} == {"invite", "reset"}
    inv = next(i for i in r["items"] if i["key"] == "invite")
    assert inv["customised"] is False and "{{link}}" in inv["body"] and set(inv["variables"]) == set(T.VARIABLES)


@pytest.mark.parametrize("subject,body,fragment", [
    ("Hi", "no link here", "{{link}}"),
    ("Hi", "Click {{link}} and {{password}}", "Unknown variable"),
    ("Hi\nBcc: x@evil.test", "{{link}}", "single line"),
    ("Hi {{org_name", "{{link}}", "not part of"),
    ("Hi", "{{link}} \x07", "Control characters"),
])
def test_template_edits_are_validated(admin, subject, body, fragment):
    r = admin.put("/admin/email-templates/invite", {"subject": subject, "body": body})
    assert r.status_code == 422 and fragment in r.json()["detail"]
    assert admin.post("/admin/email-templates/invite/preview", {"subject": subject, "body": body}).status_code == 422
    assert admin.put("/admin/email-templates/nope", {"subject": "a", "body": "{{link}}"}).status_code == 404


def test_preview_does_not_save_and_uses_sample_data(admin):
    admin.put("/admin/branding", {"display_name": "Acme"})
    p = admin.post("/admin/email-templates/reset/preview", {"subject": "{{org_name}} reset", "body": "Hi {{ first_name }}: {{link}}"}).json()
    assert p["subject"] == "Acme reset" and p["body"].startswith("Hi Alex: https://example.invalid/")
    assert admin.get("/admin/email-templates").json()["items"][1]["customised"] is False


def test_custom_template_is_used_for_real_email_and_can_be_reset(db, admin, outbox):
    admin.put("/admin/branding", {"display_name": "Acme Corp"})
    r = admin.put("/admin/email-templates/invite", {"subject": "Welcome to {{org_name}}, {{first_name}}", "body": "Join {{org_name}} here: {{link}} (valid {{valid_for}})"})
    assert r.status_code == 200 and r.json()["customised"] is True
    uid = admin.post("/admin/users", {"email": "tpl@example.com", "first_name": "Tess", "last_name": "T", "send_invite": True}).json()["id"]
    msg = outbox[-1]
    assert msg["Subject"] == "Welcome to Acme Corp, Tess"
    assert re.search(r"Join Acme Corp here: http\S+#token=\S+ \(valid 72 hours\)", msg.get_content())
    admin.delete("/admin/email-templates/invite")
    admin.post(f"/admin/users/{uid}/send-invite")
    assert outbox[-1]["Subject"] == "You have been invited to Acme Corp"          # built-in text, still branded


def test_defaults_match_the_pre_branding_wording(db, admin, outbox):
    admin.post("/admin/users", {"email": "plain@example.com", "first_name": "Pat", "last_name": "P", "send_invite": True})
    m = outbox[-1]
    assert m["Subject"] == "You have been invited to IdentityForge"
    assert "Hello Pat," in m.get_content() and "expires in 72 hours" in m.get_content()


def test_values_cannot_inject_headers_or_more_variables(db, admin, outbox):
    admin.put("/admin/email-templates/invite", {"subject": "For {{first_name}}", "body": "{{first_name}} {{link}}"})
    u = admin.post("/admin/users", {"email": "inj@example.com", "first_name": "Ok", "last_name": "X", "send_invite": True}).json()
    from backend.app.users.model import User

    row = db.get(User, u["id"])
    row.first_name = "Evil\r\nBcc: attacker@evil.test {{link}}"
    db.commit()
    admin.post(f"/admin/users/{u['id']}/send-invite")
    msg = outbox[-1]
    assert "\n" not in msg["Subject"] and "Bcc" not in msg.keys()
    body = msg.get_content()
    assert body.count("#token=") == 1                                              # the {{link}} inside the name was not expanded


def test_stored_template_that_no_longer_validates_falls_back(db, admin, outbox):
    from backend.app.branding.models import EmailTemplate

    db.add(EmailTemplate(key="reset", subject="Broken", body="no link at all"))
    db.commit()
    subject, body = T.compose(db, "reset", first_name="A", link="https://x.test/l", valid_for="1 hour")
    assert "https://x.test/l" in body and subject.startswith("Reset your")


def test_send_test_goes_only_to_the_signed_in_admin(admin, outbox):
    draft = {"subject": "Hi {{first_name}}", "body": "Link {{link}}"}
    r = admin.post("/admin/email-templates/invite/send-test", draft)
    assert r.status_code == 200 and r.json()["sent_to"] == admin.user.email
    assert outbox[-1]["To"] == admin.user.email and outbox[-1]["Subject"].startswith("[Test] ")
    assert "to" not in admin.post("/admin/email-templates/invite/send-test", {**draft, "to": "victim@example.com"}).json()
    assert outbox[-1]["To"] == admin.user.email


def test_send_test_needs_mail(admin, monkeypatch):
    monkeypatch.setattr(mailer, "configured", lambda: False)
    assert admin.post("/admin/email-templates/reset/send-test", {"subject": "a", "body": "{{link}}"}).status_code == 409


def test_template_endpoints_require_an_admin(member):
    assert member.get("/admin/email-templates").status_code == 403
    assert member.put("/admin/email-templates/invite", {"subject": "a", "body": "{{link}}"}).status_code == 403
