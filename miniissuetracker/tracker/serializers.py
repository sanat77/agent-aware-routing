"""Convert domain objects into JSON-safe dictionaries."""
from .timeutil import is_overdue


def display_name(user):
    """Full name when set, otherwise the username."""
    if user.full_name and user.full_name.strip():
        return user.full_name.strip()
    return user.username


def user_to_dict(user, include_email=False):
    data = {
        "id": user.id,
        "username": user.username,
        "display_name": display_name(user),
        "is_admin": bool(user.is_admin),
        "created_at": user.created_at,
    }
    if include_email:
        data["email"] = user.email
    return data


def task_to_dict(task, now):
    return {
        "id": task.id,
        "ticket": f"MIT-{task.ticket_number}",
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "priority": task.priority,
        "owner_id": task.owner_id,
        "assignee_id": task.assignee_id,
        "due_at": task.due_at,
        "is_overdue": is_overdue(task.due_at, task.status, now),
        "tags": list(task.tags),
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }
