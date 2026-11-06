"""Operator recovery CLI."""

import pytest

from backend.app.audit.model import AuditAction, AuditEvent
from backend.app.users.model import User
from backend.cli import main, reset_factors
from tests.conftest import STRONG, Api, make_user
from tests.test_mfa import enrol


def test_unlocks_a_super_admin_who_lost_every_factor(db, super_admin, capsys):
    enrol(super_admin, db, super_admin.user.email)
    assert Api().login(super_admin.user.email).json()["mfa_required"] is True

    assert main(["reset-factors", super_admin.user.email, "--yes"]) == 0

    r = Api().login(super_admin.user.email, STRONG)
    assert r.status_code == 200 and r.json()["success"] is True  # password alone works again
    assert super_admin.get("/me").status_code == 401  # old sessions ended

    db.expire_all()
    ev = db.query(AuditEvent).filter_by(action=AuditAction.MFA_RESET).one()
    assert ev.actor_id is None and ev.event_metadata["via"] == "cli"


def test_clears_policy_and_lockout(db):
    u = make_user(db, "locked@example.com")
    u.passkey_required = True
    u.failed_login_attempts = 3
    from datetime import datetime, timedelta, timezone

    u.lockout_until = datetime.now(timezone.utc) + timedelta(minutes=10)
    db.commit()
    assert main(["reset-factors", "LOCKED@example.com", "-y"]) == 0
    db.expire_all()
    u = db.query(User).filter_by(email="locked@example.com").one()
    assert not u.passkey_required and u.lockout_until is None and u.failed_login_attempts == 0


def test_unknown_user_is_an_error(db):
    assert main(["reset-factors", "nobody@example.com", "-y"]) == 1


def test_prompt_decline_changes_nothing(db, super_admin):
    enrol(super_admin, db, super_admin.user.email)
    assert reset_factors(super_admin.user.email, confirm=lambda _: "n", out=lambda *_: None) == 2
    assert Api().login(super_admin.user.email).json()["mfa_required"] is True


def test_does_not_change_the_password(db, member):
    before = db.query(User).filter_by(email="member@example.com").one().password_hash
    assert main(["reset-factors", "member@example.com", "-y"]) == 0
    db.expire_all()
    assert db.query(User).filter_by(email="member@example.com").one().password_hash == before


def test_cli_rotate_signing_key(db):
    from backend.cli import rotate_signing_key
    from backend.app.oidc import keys

    keys.signing_key(db)
    lines = []
    assert rotate_signing_key(out=lines.append) == 0
    assert "pending" in lines[0]
    assert rotate_signing_key(out=lines.append) == 1  # rotation already in progress
    assert rotate_signing_key(emergency=True, confirm=lambda _: "n", out=lines.append) == 2
    assert rotate_signing_key(emergency=True, assume_yes=True, out=lines.append) == 0
