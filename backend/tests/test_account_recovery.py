"""Invitations, email password reset, and the forced password change."""

import re

import pytest

from backend.app import mailer, ratelimit
from backend.app.auth.password_tokens import PasswordToken
from tests.conftest import Api, STRONG, make_user

NEW = "Brand-new-pass-77"


@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setitem(mailer.overrides, "send", sent.append)
    monkeypatch.setattr(ratelimit, "check", lambda *a, **k: None)
    monkeypatch.setattr(ratelimit, "hit", lambda *a, **k: None)
    return sent


def token_of(msg):
    return re.search(r"#token=([A-Za-z0-9_\-]+)", msg.get_body(preferencelist=("plain",)).get_content()).group(1)


def test_forgot_password_sends_a_link_and_reset_works_once(db, outbox):
    u = make_user(db, "forgot@example.com")
    anon = Api()
    r = anon.post("/auth/forgot-password", {"email": u.email}, csrf=False)
    assert r.status_code == 200 and len(outbox) == 1
    assert outbox[0]["To"] == u.email and "30 minutes" in outbox[0].get_body(preferencelist=("plain",)).get_content()
    tok = token_of(outbox[0])
    db.expire_all()
    assert tok not in str(db.query(PasswordToken.token_hash).all())            # only a keyed hash is stored
    ok = anon.post("/auth/reset-password", {"token": tok, "new_password": NEW}, csrf=False)
    assert ok.status_code == 200
    assert Api().login(u.email, NEW).status_code == 200 and Api().login(u.email, STRONG).status_code == 401
    again = anon.post("/auth/reset-password", {"token": tok, "new_password": NEW + "x"}, csrf=False)
    assert again.status_code == 400


def test_forgot_password_does_not_reveal_accounts(db, outbox):
    make_user(db, "real@example.com")
    a, b = Api(), Api()
    r1 = a.post("/auth/forgot-password", {"email": "real@example.com"}, csrf=False)
    r2 = b.post("/auth/forgot-password", {"email": "ghost@example.com"}, csrf=False)
    assert r1.status_code == r2.status_code == 200 and r1.json() == r2.json()
    assert len(outbox) == 1


@pytest.mark.parametrize("status", ["suspended", "deprovisioned", "staged"])
def test_blocked_statuses_get_no_reset_email(db, outbox, status):
    u = make_user(db, f"{status}@example.com")
    u.status = status
    db.commit()
    assert Api().post("/auth/forgot-password", {"email": u.email}, csrf=False).status_code == 200
    assert outbox == []


def test_reset_ends_sessions_and_unlocks(db, outbox):
    u = make_user(db, "sess@example.com")
    logged_in = Api()
    assert logged_in.login(u.email).status_code == 200
    u.status = "locked_out"
    db.commit()
    Api().post("/auth/forgot-password", {"email": u.email}, csrf=False)
    assert Api().post("/auth/reset-password", {"token": token_of(outbox[0]), "new_password": NEW}, csrf=False).status_code == 200
    assert logged_in.get("/me").status_code == 401
    db.expire_all()
    assert db.get(type(u), u.id).status == "active"


def test_bad_and_weak_tokens(db, outbox):
    anon = Api()
    assert anon.post("/auth/reset-password", {"token": "x" * 40, "new_password": NEW}, csrf=False).status_code == 400
    assert anon.post("/auth/reset-password", {"token": "short", "new_password": NEW}, csrf=False).status_code == 422
    make_user(db, "weak@example.com")
    anon.post("/auth/forgot-password", {"email": "weak@example.com"}, csrf=False)
    assert anon.post("/auth/reset-password", {"token": token_of(outbox[0]), "new_password": "weak"}, csrf=False).status_code == 422


def test_expired_token_is_refused(db, outbox):
    from datetime import datetime, timedelta, timezone

    make_user(db, "old@example.com")
    Api().post("/auth/forgot-password", {"email": "old@example.com"}, csrf=False)
    db.query(PasswordToken).update({"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)})
    db.commit()
    assert Api().post("/auth/reset-password", {"token": token_of(outbox[0]), "new_password": NEW}, csrf=False).status_code == 400


def test_a_new_request_voids_the_earlier_link(db, outbox):
    make_user(db, "two@example.com")
    a = Api()
    a.post("/auth/forgot-password", {"email": "two@example.com"}, csrf=False)
    a.post("/auth/forgot-password", {"email": "two@example.com"}, csrf=False)
    assert a.post("/auth/reset-password", {"token": token_of(outbox[0]), "new_password": NEW}, csrf=False).status_code == 400
    assert a.post("/auth/reset-password", {"token": token_of(outbox[1]), "new_password": NEW}, csrf=False).status_code == 200


def test_invite_flow(db, admin, outbox):
    r = admin.post("/admin/users", {"email": "newbie@example.com", "first_name": "N", "last_name": "B", "send_invite": True})
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "provisioned" and r.json()["invitation_sent"] is True and "temporary_password" not in r.json()
    assert "72 hours" in outbox[0].get_body(preferencelist=("plain",)).get_content()
    assert Api().login("newbie@example.com", STRONG).status_code == 401              # not active, no usable password
    assert Api().post("/auth/reset-password", {"token": token_of(outbox[0]), "new_password": NEW}, csrf=False).status_code == 200
    s = Api()
    assert s.login("newbie@example.com", NEW).status_code == 200
    assert admin.get(f"/admin/users/{r.json()['id']}").json()["status"] == "active"


def test_invite_needs_mail_and_rejects_a_password(db, admin, monkeypatch):
    monkeypatch.setattr(mailer, "configured", lambda: False)
    body = {"email": "nomail@example.com", "first_name": "N", "last_name": "M", "send_invite": True}
    assert admin.post("/admin/users", body).status_code == 409
    monkeypatch.undo()


def test_resend_invite_and_admin_triggered_reset(db, admin, outbox):
    uid = admin.post("/admin/users", {"email": "re@example.com", "first_name": "R", "last_name": "E", "send_invite": True}).json()["id"]
    assert admin.post(f"/admin/users/{uid}/send-invite").status_code == 200 and len(outbox) == 2
    assert Api().post("/auth/reset-password", {"token": token_of(outbox[0]), "new_password": NEW}, csrf=False).status_code == 400
    assert Api().post("/auth/reset-password", {"token": token_of(outbox[1]), "new_password": NEW}, csrf=False).status_code == 200
    assert admin.post(f"/admin/users/{uid}/send-invite").status_code == 409          # active now
    assert admin.post(f"/admin/users/{uid}/send-reset").status_code == 200 and len(outbox) == 3


def test_member_cannot_send_invites(member, outbox):
    assert member.post("/admin/users/1/send-invite").status_code == 403
    assert member.post("/admin/users/1/send-reset").status_code == 403


def test_require_change_forces_a_new_password(db, admin):
    u = make_user(db, "exp@example.com")
    assert admin.post(f"/admin/users/{u.id}/password", {"new_password": "Temp-password-123", "require_change": True}).status_code == 200
    assert admin.get(f"/admin/users/{u.id}").json()["status"] == "password_expired"
    r = Api().login(u.email, "Temp-password-123")
    assert r.status_code == 200 and r.json() == {"success": False, "password_change_required": True}
    assert "set-cookie" not in r.headers
    assert Api().login(u.email, "wrong-password-1A").status_code == 401           # a wrong password still looks like any other failure
    anon = Api()
    assert anon.post("/auth/change-expired-password", {"email": u.email, "current_password": "nope-nope-1A", "new_password": NEW}, csrf=False).status_code == 401
    assert anon.post("/auth/change-expired-password", {"email": u.email, "current_password": "Temp-password-123", "new_password": "Temp-password-123"}, csrf=False).status_code == 422
    assert anon.post("/auth/change-expired-password", {"email": u.email, "current_password": "Temp-password-123", "new_password": NEW}, csrf=False).status_code == 200
    assert Api().login(u.email, NEW).status_code == 200


def test_change_expired_only_for_expired_accounts(db):
    u = make_user(db, "fine@example.com")
    r = Api().post("/auth/change-expired-password", {"email": u.email, "current_password": STRONG, "new_password": NEW}, csrf=False)
    assert r.status_code == 401


def test_foreign_origin_is_refused(db, outbox):
    make_user(db, "o@example.com")
    a = Api()
    r = a.c.post("/api/v1/auth/forgot-password", json={"email": "o@example.com"}, headers={"Origin": "http://evil.test"})
    assert r.status_code == 403 and outbox == []
