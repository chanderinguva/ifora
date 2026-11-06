"""Group model for identity management."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from sqlalchemy import Column, DateTime, Integer, String, Boolean, ForeignKey, Table
from sqlalchemy.orm import relationship

from backend.app.db import Base


# Association table for user-group membership
user_group_association = Table(
    "user_group_membership",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("group_id", Integer, ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True),
    Column("added_by_user_id", Integer, ForeignKey("users.id"), nullable=True),
    Column("added_at", DateTime(timezone=True), default=datetime.utcnow, nullable=False),
)


class GroupRole(str, Enum):
    """Role within a group."""

    MEMBER = "member"
    MODERATOR = "moderator"
    MANAGER = "manager"
    OWNER = "owner"


class Group(Base):
    """Group model for organizing users."""

    __tablename__ = "groups"

    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Core identity
    name = Column(String(100), nullable=False)
    description = Column(String(500), nullable=True)

    # Group type
    is_system_group = Column(Boolean, default=False, nullable=False)
    type = Column(String(50), default="standard", nullable=False)

    # Extensible attributes
    attributes = Column(String, nullable=True)

    # Metadata
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Memberships
    members = relationship(
        "User",
        secondary=user_group_association,
        primaryjoin=lambda: Group.id == user_group_association.c.group_id,
        secondaryjoin=lambda: user_group_association.c.user_id == __import__("backend.app.users.model", fromlist=["User"]).User.id,
        backref="groups",
        lazy="selectin",
    )

    member_count = Column(Integer, default=0, nullable=False)

    def __init__(
        self,
        name: str,
        description: Optional[str] = None,
        is_system_group: bool = False,
        group_type: str = "standard",
    ):
        self.name = name
        self.description = description
        self.is_system_group = is_system_group
        self.type = group_type

    def get_attributes(self) -> Dict[str, Any]:
        """Get group attributes as dictionary."""
        if self.attributes:
            try:
                import json

                return json.loads(self.attributes)
            except (json.JSONDecodeError, TypeError):
                return {}
        return {}

    def set_attributes(self, attributes: Dict[str, Any]) -> None:
        """Set group attributes from dictionary."""
        import json

        self.attributes = json.dumps(attributes)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "is_system_group": self.is_system_group,
            "type": self.type,
            "attributes": self.get_attributes(),
            "member_count": len(self.members),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }