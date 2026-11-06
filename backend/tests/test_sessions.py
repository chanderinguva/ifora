"""Session model tests."""

import pytest
from datetime import datetime, timedelta
from backend.app.auth.session import Session, SessionStatus


class TestSessionModel:
    """Tests for Session model."""

    def test_session_creation(self):
        """Test session creation with all required fields."""
        session = Session.create(
            user_id=1,
            session_lifetime_hours=8,
            ip_address="192.168.1.1",
            user_agent="TestBrowser/1.0",
            is_admin_session=True,
        )

        assert session.user_id == 1
        assert session.status == SessionStatus.ACTIVE.value
        assert session.ip_address == "192.168.1.1"
        assert session.user_agent == "TestBrowser/1.0"
        assert session.is_admin_session is True

    def test_session_token_generation(self):
        """Test session token is cryptographically secure."""
        session1 = Session.create(user_id=1)
        session2 = Session.create(user_id=2)

        # Tokens should be different
        assert session1.token != session2.token

        # Token should be a valid URL-safe string
        import re

        assert re.match(r"^[A-Za-z0-9_-]+$", session1.token)

        # Token should have sufficient length (256 bits base64 encoded)
        assert len(session1.token) >= 43

    def test_session_expiration(self):
        """Test session expiration check."""
        session = Session.create(
            user_id=1,
            session_lifetime_hours=8,
        )

        # Session should not be expired initially
        assert not session.is_expired

        # Test with already expired session
        session.expires_at = datetime.utcnow() - timedelta(hours=1)
        session.status = SessionStatus.EXPIRED.value

        assert session.is_expired

    def test_session_revoke(self):
        """Test session revocation."""
        session = Session.create(user_id=1)

        assert session.status == SessionStatus.ACTIVE.value

        session.revoke()

        assert session.status == SessionStatus.REVOKED.value

    def test_session_extend(self):
        """Test session extension."""
        session = Session.create(
            user_id=1,
            session_lifetime_hours=1,
        )

        original_expires = session.expires_at
        session.extend(additional_hours=8)

        # Expires should be extended
        assert session.expires_at > original_expires

    def test_session_touch(self):
        """Test session activity update."""
        session = Session.create(
            user_id=1,
            session_lifetime_hours=8,
        )

        original_activity = session.last_activity_at
        import time

        time.sleep(0.1)
        session.touch()

        # Last activity should be updated
        assert session.last_activity_at > original_activity

    def test_session_to_dict(self):
        """Test session serialization to dictionary."""
        session = Session.create(
            user_id=1,
            session_lifetime_hours=8,
            ip_address="192.168.1.1",
        )
        session.id = 1

        result = session.to_dict()

        assert result["user_id"] == 1
        assert result["is_admin_session"] is False
        assert "expires_at" in result
        assert "created_at" in result