"""Core data models."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class User:
    """An application user account."""

    user_id: str
    username: str
    email: str | None = None
    is_active: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Session:
    """A persisted login session bound to a user."""

    session_id: str
    user_id: str
    expires_at: datetime
    revoked: bool = False

    def is_valid(self) -> bool:
        return not self.revoked and datetime.utcnow() < self.expires_at
