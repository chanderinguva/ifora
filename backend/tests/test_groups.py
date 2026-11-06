"""Group model tests."""

import pytest
from datetime import datetime
from backend.app.groups.model import Group, GroupRole


class TestGroupModel:
    """Tests for Group model."""

    def test_group_creation(self):
        """Test group creation with all required fields."""
        group = Group(
            name="Engineering",
            description="Engineering department members",
        )

        assert group.name == "Engineering"
        assert group.description == "Engineering department members"
        assert group.is_system_group is False
        assert group.type == "standard"
        assert group.member_count == 0

    def test_system_group_creation(self):
        """Test system group creation."""
        group = Group(
            name="System Users",
            is_system_group=True,
            group_type="system",
        )

        assert group.name == "System Users"
        assert group.is_system_group is True
        assert group.type == "system"

    def test_group_attributes(self):
        """Test group attributes getter and setter."""
        group = Group(name="Test Group")

        attrs = {"color": "blue", "icon": "folder"}
        group.set_attributes(attrs)

        assert group.get_attributes() == attrs

    def test_group_to_dict(self):
        """Test group serialization to dictionary."""
        group = Group(
            name="Test Group",
            description="Test description",
        )
        group.id = 1
        group.created_at = datetime(2024, 1, 1)
        group.updated_at = datetime(2024, 1, 1)
        group.member_count = 5

        result = group.to_dict()

        assert result["name"] == "Test Group"
        assert result["description"] == "Test description"
        assert result["member_count"] == 5