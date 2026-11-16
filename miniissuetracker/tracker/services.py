"""Business logic. Services raise ApiError subclasses; the HTTP layer turns them into responses."""
import sqlite3

from . import auth
from .errors import (
    AuthenticationError,
    ConflictError,
    InvalidTransitionError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from .models import DEFAULT_STATUS, STATUSES, TERMINAL_STATUSES, can_transition
from .pagination import page_metadata, parse_page_request
from .query import build_filters, order_by_sql, parse_sort
from .retry import retry_call
from .serializers import task_to_dict, user_to_dict
from .timeutil import format_datetime
from .validation import validate_task_payload, validate_user_payload


class UserService:
    def __init__(self, users, config, clock):
        self.users = users
        self.config = config
        self.clock = clock

    def register(self, payload, is_admin=False):
        data = validate_user_payload(payload)
        user = self.users.insert(
            data["username"],
            data["email"],
            data["full_name"],
            auth.hash_password(data["password"]),
            is_admin,
            format_datetime(self.clock.now()),
        )
        return user

    def login(self, username, password):
        user = self.users.find_by_username(username or "")
        if user is None or not auth.verify_password(password or "", user.password_hash):
            raise AuthenticationError("invalid username or password")
        token = auth.issue_token(user.id, self.config.secret_key, self.config.token_ttl_seconds, self.clock.now())
        return {"token": token, "expires_in": self.config.token_ttl_seconds}

    def authenticate(self, header_value):
        token = auth.parse_authorization_header(header_value)
        user_id = auth.verify_token(token, self.config.secret_key, self.clock.now())
        try:
            return self.users.get(user_id)
        except NotFoundError as exc:
            raise AuthenticationError("unknown user") from exc

    def get_profile(self, viewer, user_id):
        user = self.users.get(user_id)
        return user_to_dict(user, include_email=auth.can_view_user_email(viewer, user))


class TaskService:
    def __init__(self, tasks, users, config, clock, cache, idempotency, sequence):
        self.tasks = tasks
        self.users = users
        self.config = config
        self.clock = clock
        self.cache = cache
        self.idempotency = idempotency
        self.sequence = sequence

    # -- helpers --------------------------------------------------------
    def _now_iso(self):
        return format_datetime(self.clock.now())

    def _serialize(self, task):
        return task_to_dict(task, self.clock.now())

    def _load(self, task_id):
        key = f"task:{task_id}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        task = retry_call(lambda: self.tasks.get(task_id), attempts=self.config.retry_attempts)
        self.cache.set(key, task)
        return task

    def _invalidate(self, task_id):
        self.cache.invalidate(f"task:{task_id}")
        self.cache.invalidate_prefix("stats:")

    def _check_assignee(self, data):
        assignee = data.get("assignee_id")
        if assignee is not None and not self.users.exists(assignee):
            raise ValidationError("assignee does not exist", {"assignee_id": "unknown_user"})

    # -- commands -------------------------------------------------------
    def create_task(self, user, payload, idempotency_key=None):
        if idempotency_key:
            previous = self.idempotency.lookup(idempotency_key, user.id, payload)
            if previous is not None:
                return previous
        data = validate_task_payload(payload, default_priority=self.config.default_priority)
        self._check_assignee(data)
        try:
            task = self.tasks.insert(self.sequence.next(), user.id, data, DEFAULT_STATUS, self._now_iso())
        except sqlite3.IntegrityError as exc:
            raise ConflictError("task could not be created") from exc
        self.cache.invalidate_prefix("stats:")
        result = (201, self._serialize(task))
        if idempotency_key:
            self.idempotency.save(idempotency_key, user.id, payload, *result)
        return result

    def get_task(self, task_id):
        return self._serialize(self._load(task_id))

    def update_task(self, user, task_id, payload):
        task = self._load(task_id)
        if not auth.can_edit_task(user, task):
            raise PermissionDeniedError("only the owner or an admin can edit this task")
        changes = validate_task_payload(payload, partial=True)
        if "status" in changes:
            raise ValidationError("use the status endpoint to change status", {"status": "read_only"})
        self._check_assignee(changes)
        updated = self.tasks.update(task_id, changes, self._now_iso())
        self._invalidate(task_id)
        return self._serialize(updated)

    def change_status(self, user, task_id, target):
        task = self._load(task_id)
        if not auth.can_change_status(user, task):
            raise PermissionDeniedError("not allowed to change the status of this task")
        if target not in STATUSES:
            raise ValidationError("unknown status", {"status": "invalid"})
        if not can_transition(task.status, target):
            raise InvalidTransitionError(f"cannot move task from {task.status} to {target}")
        updated = self.tasks.update(task_id, {"status": target}, self._now_iso())
        self._invalidate(task_id)
        return self._serialize(updated)

    def delete_task(self, user, task_id):
        task = self._load(task_id)
        if not auth.can_delete_task(user, task):
            raise PermissionDeniedError("only the owner or an admin can delete this task")
        self.tasks.delete(task_id)
        self._invalidate(task_id)

    # -- queries --------------------------------------------------------
    def list_tasks(self, params):
        page = parse_page_request(params, self.config)
        order = parse_sort(params.get("sort"))
        where_sql, args = build_filters(params, now_iso=self._now_iso())
        total = self.tasks.count(where_sql, args)
        items = self.tasks.list(where_sql, args, order_by_sql(order), page.limit, page.offset)
        return {"items": [self._serialize(t) for t in items], "meta": page_metadata(total, page)}

    def stats(self, owner_id=None):
        key = f"stats:{owner_id or 'all'}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        counts = self.tasks.status_counts(owner_id)
        priorities = self.tasks.priorities(owner_id)
        total = sum(counts.values())
        finished = sum(counts[s] for s in TERMINAL_STATUSES)
        result = {
            "total": total,
            "by_status": counts,
            "completion_rate": round(finished / total, 4) if total else 0.0,
            "average_priority": round(sum(priorities) / len(priorities), 2) if priorities else None,
            "open_count": total - finished,
        }
        self.cache.set(key, result)
        return result
