"""Date/time helpers. All timestamps are stored and returned in UTC ISO-8601 with a 'Z' suffix."""
from datetime import datetime, time, timedelta, timezone

from .errors import ValidationError

ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class Clock:
    """Injectable clock so tests can control 'now'."""

    def __init__(self, fixed=None):
        self.fixed = fixed

    def now(self):
        if self.fixed is not None:
            return self.fixed
        return datetime.now(timezone.utc).replace(microsecond=0)

    def advance(self, seconds):
        self.fixed = self.now() + timedelta(seconds=seconds)


def format_datetime(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime(ISO_FORMAT)


def parse_datetime(value, field="due_at"):
    """Parse an ISO date or datetime string into an aware UTC datetime.

    A bare date (YYYY-MM-DD) means the end of that day in UTC.
    Naive datetimes are interpreted as UTC.
    """
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be an ISO-8601 string", {field: "invalid"})
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        if len(text) == 10:
            day = datetime.strptime(text, "%Y-%m-%d").date()
            return datetime.combine(day, time(23, 59, 59), tzinfo=timezone.utc)
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValidationError(f"{field} is not a valid date", {field: "invalid"}) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0)


def is_overdue(due_at, status, now):
    """A task is overdue when its due time is strictly in the past and it is not finished."""
    if due_at is None or status in ("done", "closed"):
        return False
    due = parse_datetime(due_at) if isinstance(due_at, str) else due_at
    return due < now
