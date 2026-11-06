"""User model tests."""

import pytest
from datetime import datetime
from backend.app.users.model import User, UserStatus


class TestUserModel:
    """Tests for User model."""

    def test_user_creation(self):
        """Test user creation with all required fields."""
        user = User(
            email="test@example.com",
            username="testuser",
            first_name="Test",
            last_name="User",
            password="securepassword123",
        )

        assert user.email == "test@example.com"
        assert user.username == "testuser"
        assert user.first_name == "Test"
        assert user.last_name == "User"
        assert user.status == UserStatus.ACTIVE.value
        assert not user.is_admin
        assert not user.is_super_admin

    def test_user_password_hashing(self):
        """Test password is properly hashed."""
        user = User(
            email="hash@example.com",
            username="hashuser",
            first_name="Hash",
            last_name="Test",
            password="mypassword123",
        )

        # Password should be hashed, not plaintext
        assert user.password_hash != "mypassword123"
        assert len(user.password_hash) > 20

    def test_user_password_verification(self):
        """Test password verification works correctly."""
        user = User(
            email="verify@example.com",
            username="verifyuser",
            first_name="Verify",
            last_name="Test",
            password="correctpassword",
        )

        # Correct password should verify
        assert user.verify_password("correctpassword") is True

        # Wrong password should not verify
        assert user.verify_password("wrongpassword") is False

    def test_user_name_property(self):
        """Test user name property returns full name."""
        user = User(
            email="name@example.com",
            username="nameuser",
            first_name="John",
            last_name="Doe",
            password="password123",
        )

        assert user.name == "John Doe"

    def test_user_profile_attributes(self):
        """Test profile attributes getter and setter."""
        user = User(
            email="profile@example.com",
            username="profileuser",
            first_name="Profile",
            last_name="Test",
            password="password123",
        )

        # Set profile attributes
        attrs = {"department": "Engineering", "position": "Developer"}
        user.set_profile_attributes(attrs)

        # Get profile attributes
        assert user.get_profile_attributes() == attrs

    def test_user_to_dict(self):
        """Test user serialization to dictionary."""
        user = User(
            email="dict@example.com",
            username="dictuser",
            first_name="Dict",
            last_name="Test",
            password="password123",
            is_admin=True,
        )
        user.id = 1
        user.created_at = datetime(2024, 1, 1)
        user.updated_at = datetime(2024, 1, 1)
        user.last_login_at = datetime(2024, 1, 2)

        result = user.to_dict()

        assert result["email"] == "dict@example.com"
        assert result["username"] == "dictuser"
        assert result["is_admin"] is True
        assert result["status"] == UserStatus.ACTIVE.value