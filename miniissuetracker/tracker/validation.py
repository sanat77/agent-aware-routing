"""Input validation for API payloads. Returns cleaned dictionaries or raises ValidationError."""
import re

from .convert import parse_int
from .errors import ValidationError
from .models import STATUSES
from .timeutil import format_datetime, parse_datetime

TITLE_MIN = 1
TITLE_MAX = 120
PRIORITY_MIN = 1
PRIORITY_MAX = 5
TAG_MAX_LENGTH = 30
MAX_TAGS = 10
USERNAME_RE = re.compile(r"^[a-z0-9_]{3,32}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")
PASSWORD_MIN = 8

TASK_FIELDS = {"title", "description", "priority", "assignee_id", "due_at", "tags", "status"}


def _clean_title(value):
    if value is None:
        raise ValidationError("title is required", {"title": "required"})
    if not isinstance(value, str):
        raise ValidationError("title must be a string", {"title": "invalid"})
    title = value.strip()
    if len(title) < TITLE_MIN:
        raise ValidationError("title must not be empty", {"title": "empty"})
    if len(title) > TITLE_MAX:
        raise ValidationError(f"title must be at most {TITLE_MAX} characters", {"title": "too_long"})
    return title


def _clean_description(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError("description must be a string", {"description": "invalid"})
    text = value.strip()
    return text or None


def _clean_priority(value):
    priority = parse_int(value, name="priority")
    if priority is None:
        raise ValidationError("priority must not be null", {"priority": "required"})
    if priority < PRIORITY_MIN or priority > PRIORITY_MAX:
        raise ValidationError(
            f"priority must be between {PRIORITY_MIN} and {PRIORITY_MAX}", {"priority": "out_of_range"}
        )
    return priority


def _clean_tags(value):
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValidationError("tags must be a list", {"tags": "invalid"})
    cleaned = []
    for tag in value:
        if not isinstance(tag, str) or not tag.strip():
            raise ValidationError("tags must be non-empty strings", {"tags": "invalid"})
        tag = tag.strip().lower()
        if len(tag) > TAG_MAX_LENGTH:
            raise ValidationError("tag too long", {"tags": "too_long"})
        if tag not in cleaned:
            cleaned.append(tag)
    if len(cleaned) > MAX_TAGS:
        raise ValidationError(f"at most {MAX_TAGS} tags allowed", {"tags": "too_many"})
    return cleaned


def validate_task_payload(data, partial=False, default_priority=3):
    if not isinstance(data, dict):
        raise ValidationError("request body must be a JSON object")
    unknown = set(data) - TASK_FIELDS
    if unknown:
        raise ValidationError("unknown fields", {name: "unknown" for name in sorted(unknown)})
    cleaned = {}
    if "title" in data or not partial:
        cleaned["title"] = _clean_title(data.get("title"))
    if "description" in data or not partial:
        cleaned["description"] = _clean_description(data.get("description"))
    if "priority" in data:
        cleaned["priority"] = _clean_priority(data["priority"])
    elif not partial:
        cleaned["priority"] = default_priority
    if "assignee_id" in data or not partial:
        cleaned["assignee_id"] = parse_int(data.get("assignee_id"), name="assignee_id")
    if "due_at" in data or not partial:
        due = parse_datetime(data.get("due_at"))
        cleaned["due_at"] = format_datetime(due)
    if "tags" in data or not partial:
        cleaned["tags"] = _clean_tags(data.get("tags"))
    if "status" in data:
        if not partial:
            raise ValidationError("status cannot be set on create", {"status": "read_only"})
        if data["status"] not in STATUSES:
            raise ValidationError("unknown status", {"status": "invalid"})
        cleaned["status"] = data["status"]
    return cleaned


def validate_user_payload(data):
    if not isinstance(data, dict):
        raise ValidationError("request body must be a JSON object")
    errors = {}
    username = data.get("username")
    email = data.get("email")
    password = data.get("password")
    full_name = data.get("full_name")
    if not isinstance(username, str) or not USERNAME_RE.match(username):
        errors["username"] = "invalid"
    if not isinstance(email, str) or not EMAIL_RE.match(email.strip()):
        errors["email"] = "invalid"
    if not isinstance(password, str) or len(password) < PASSWORD_MIN:
        errors["password"] = "too_short"
    if full_name is not None and not isinstance(full_name, str):
        errors["full_name"] = "invalid"
    if errors:
        raise ValidationError("invalid user", errors)
    return {
        "username": username,
        "email": email.strip().lower(),
        "password": password,
        "full_name": (full_name or "").strip() or None,
    }
