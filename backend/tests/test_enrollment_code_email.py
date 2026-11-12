"""Admins who must enrol a first factor can have the one-time enrolment code emailed to themselves."""

import re

import pytest

from backend.app import mailer
from backend.app.audit.model import AuditAction, AuditEvent
from backend.app.config import settings
from tests.test_mfa import enrol
from tests.test_passkeys import register


@pytest.fixture(autouse=True)
def on(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_MFA_REQUIRED", True)
    monkeypatch.setattr(settings, "ENROLLMENT_CODE_EMAIL", True)
    monkeypatch.setattr(mailer, "configured", lambda: True)


@pytest.fixture
def sent(monkeypatch):
    box = []
    monkeypatch.setitem(mailer.overrides, "send", box.append)
    return box


def code_from(msg):
    m = re.search(r"\b([A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4})\b", msg.get_body(preferencelist=("plain",)).get_content())
    assert m, msg.get_body(preferencelist=("plain",)).get_content()
    return m.group(1)


def test_profile_advertises_the_option_only_when_it_applies(admin, monkeypatch):
    assert admin.get("/me").json()["user"]["enrollment_code_by_email"] is True
    monkeypatch.setattr(settings, "ENROLLMENT_CODE_EMAIL", False)
    assert admin.get("/me").json()["user"]["enrollment_code_by_email"] is False
    monkeypatch.setattr(settings, "ENROLLMENT_CODE_EMAIL", True)
    monkeypatch.setattr(mailer, "configured", lambda: False)
    assert admin.get("/me").json()["user"]["enrollment_code_by_email"] is False


def test_emailed_code_goes_to_the_admins_own_address_and_enrols_a_factor(db, admin, sent):
    r = admin.post("/me/mfa/enrollment-code/email")
    assert r.status_code == 200, r.text
    assert len(sent) == 1 and sent[0]["To"] == admin.user.email
    assert "code" not in r.json()  # the code only travels by email, never in the response
    enrol(admin, db, admin.user.email, code_from(sent[0]))
    assert admin.get("/me").json()["user"]["mfa_setup_required"] is False


def test_emailed_code_also_works_for_a_passkey(admin, sent):
    admin.post("/me/mfa/enrollment-code/email")
    _, r = register(admin, enrollment_code=code_from(sent[0]))
    assert r.status_code == 201, r.text


def test_wrong_code_is_still_rejected(admin, sent):
    admin.post("/me/mfa/enrollment-code/email")
    r = admin.post("/me/mfa/setup", {"password": "x", "enrollment_code": "AAAA-AAAA-AAAA"})
    assert r.status_code in (403, 422)


def test_a_new_request_replaces_the_previous_code(admin, sent):
    admin.post("/me/mfa/enrollment-code/email")
    admin.post("/me/mfa/enrollment-code/email")
    first, second = code_from(sent[0]), code_from(sent[1])
    assert first != second
    from tests.conftest import STRONG

    assert admin.post("/me/mfa/setup", {"password": STRONG, "enrollment_code": first}).status_code == 403
    assert admin.post("/me/mfa/setup", {"password": STRONG, "enrollment_code": second}).status_code == 200


def test_requests_are_rate_limited(admin, sent):
    for _ in range(3):
        assert admin.post("/me/mfa/enrollment-code/email").status_code == 200
    assert admin.post("/me/mfa/enrollment-code/email").status_code == 429
    assert len(sent) == 3


def test_disabled_by_default_setting(admin, sent, monkeypatch):
    monkeypatch.setattr(settings, "ENROLLMENT_CODE_EMAIL", False)
    assert admin.post("/me/mfa/enrollment-code/email").status_code == 409
    assert sent == []


def test_super_admins_keep_the_operator_only_path(super_admin, sent):
    assert super_admin.get("/me").json()["user"]["enrollment_code_by_email"] is False
    assert super_admin.post("/me/mfa/enrollment-code/email").status_code == 409
    assert sent == []


def test_users_who_do_not_need_enrolment_get_nothing(member, sent):
    assert member.post("/me/mfa/enrollment-code/email").status_code == 409
    assert sent == []


def test_mail_failure_is_reported_and_audited(db, admin, monkeypatch):
    def boom(msg):
        raise OSError("smtp down")

    monkeypatch.setitem(mailer.overrides, "send", boom)
    r = admin.post("/me/mfa/enrollment-code/email")
    assert r.status_code == 502
    ev = db.query(AuditEvent).filter(AuditEvent.action == AuditAction.ENROLLMENT_CODE_ISSUED.value).first()
    assert ev is not None and (ev.event_metadata or {}).get("via") == "email"


def test_requires_a_session(sent):
    from tests.conftest import Api

    assert Api().post("/me/mfa/enrollment-code/email").status_code == 401
    assert sent == []
