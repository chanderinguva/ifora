"""User.is_active must be a real boolean: active status and not currently locked out."""

from datetime import datetime, timedelta, timezone

from tests.conftest import make_user


def test_is_active_reflects_status_and_lockout(db):
    u = make_user(db, "active@example.com")
    assert u.is_active is True
    u.lockout_until = datetime.now(timezone.utc) + timedelta(minutes=5)
    assert u.is_active is False                       # locked out right now
    u.lockout_until = datetime.now(timezone.utc) - timedelta(minutes=5)
    assert u.is_active is True                        # lockout has expired
    u.lockout_until = None
    u.status = "suspended"
    assert u.is_active is False
