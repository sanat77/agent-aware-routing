"""Domain models and the task status state machine."""
import json
from dataclasses import dataclass, field
from typing import Optional

STATUSES = ("open", "in_progress", "blocked", "done", "closed")
TERMINAL_STATUSES = ("done", "closed")
DEFAULT_STATUS = "open"

TRANSITIONS = {
    "open": {"in_progress", "closed"},
    "in_progress": {"open", "blocked", "done"},
    "blocked": {"in_progress"},
    "done": {"open", "closed"},
    "closed": set(),
}


def can_transition(current, target):
    """Return True if a task may move from `current` to `target`."""
    if current == target:
        return False
    return target in TRANSITIONS.get(current, set())


@dataclass
class User:
    id: int
    username: str
    email: str
    full_name: Optional[str]
    password_hash: str
    is_admin: bool
    created_at: str

    @classmethod
    def from_row(cls, row):
        return cls(
            id=row["id"],
            username=row["username"],
            email=row["email"],
            full_name=row["full_name"],
            password_hash=row["password_hash"],
            is_admin=bool(row["is_admin"]),
            created_at=row["created_at"],
        )


@dataclass
class Task:
    id: int
    ticket_number: int
    title: str
    description: Optional[str]
    status: str
    priority: int
    owner_id: int
    assignee_id: Optional[int]
    due_at: Optional[str]
    tags: list = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_row(cls, row):
        return cls(
            id=row["id"],
            ticket_number=row["ticket_number"],
            title=row["title"],
            description=row["description"],
            status=row["status"],
            priority=row["priority"],
            owner_id=row["owner_id"],
            assignee_id=row["assignee_id"],
            due_at=row["due_at"],
            tags=json.loads(row["tags"] or "[]"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
