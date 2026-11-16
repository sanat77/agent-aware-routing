"""SQL data access for users and tasks."""
import json
import sqlite3

from .errors import ConflictError, NotFoundError
from .models import STATUSES, Task, User


class UserRepository:
    def __init__(self, db):
        self.db = db

    def insert(self, username, email, full_name, password_hash, is_admin, created_at):
        try:
            with self.db.transaction() as conn:
                cur = conn.execute(
                    "INSERT INTO users (username, email, full_name, password_hash, is_admin, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (username, email, full_name, password_hash, int(is_admin), created_at),
                )
                user_id = cur.lastrowid
        except sqlite3.IntegrityError as exc:
            raise ConflictError("username or email already registered") from exc
        return self.get(user_id)

    def get(self, user_id):
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"user {user_id} not found")
        return User.from_row(row)

    def find_by_username(self, username):
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return User.from_row(row) if row else None

    def exists(self, user_id):
        with self.db.connection() as conn:
            row = conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone()
        return row is not None


class TaskRepository:
    COLUMNS = ("title", "description", "status", "priority", "assignee_id", "due_at", "tags")

    def __init__(self, db):
        self.db = db

    def insert(self, ticket_number, owner_id, data, status, now_iso):
        with self.db.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO tasks (ticket_number, title, description, status, priority, owner_id,"
                " assignee_id, due_at, tags, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ticket_number,
                    data["title"],
                    data.get("description"),
                    status,
                    data["priority"],
                    owner_id,
                    data.get("assignee_id"),
                    data.get("due_at"),
                    json.dumps(data.get("tags", [])),
                    now_iso,
                    now_iso,
                ),
            )
            task_id = cur.lastrowid
        return self.get(task_id)

    def get(self, task_id):
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"task {task_id} not found")
        return Task.from_row(row)

    def update(self, task_id, changes, now_iso):
        if not changes:
            return self.get(task_id)
        assignments = []
        args = []
        for column in self.COLUMNS:
            if column in changes:
                value = changes[column]
                if column == "tags":
                    value = json.dumps(value)
                assignments.append(f"{column} = ?")
                args.append(value)
        assignments.append("updated_at = ?")
        args.append(now_iso)
        args.append(task_id)
        with self.db.transaction() as conn:
            cur = conn.execute(f"UPDATE tasks SET {', '.join(assignments)} WHERE id = ?", args)
            if cur.rowcount == 0:
                raise NotFoundError(f"task {task_id} not found")
        return self.get(task_id)

    def delete(self, task_id):
        with self.db.transaction() as conn:
            cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            if cur.rowcount == 0:
                raise NotFoundError(f"task {task_id} not found")

    def list(self, where_sql, args, order_sql, limit, offset):
        sql = f"SELECT * FROM tasks WHERE {where_sql} ORDER BY {order_sql} LIMIT ? OFFSET ?"
        with self.db.connection() as conn:
            rows = conn.execute(sql, [*args, limit, offset]).fetchall()
        return [Task.from_row(row) for row in rows]

    def count(self, where_sql, args):
        with self.db.connection() as conn:
            row = conn.execute(f"SELECT COUNT(*) AS n FROM tasks WHERE {where_sql}", args).fetchone()
        return row["n"]

    def status_counts(self, owner_id=None):
        sql = "SELECT status, COUNT(*) AS n FROM tasks"
        args = []
        if owner_id is not None:
            sql += " WHERE owner_id = ?"
            args.append(owner_id)
        sql += " GROUP BY status"
        with self.db.connection() as conn:
            rows = conn.execute(sql, args).fetchall()
        counts = {status: 0 for status in STATUSES}
        for row in rows:
            counts[row["status"]] = row["n"]
        return counts

    def priorities(self, owner_id=None):
        sql = "SELECT priority FROM tasks"
        args = []
        if owner_id is not None:
            sql += " WHERE owner_id = ?"
            args.append(owner_id)
        with self.db.connection() as conn:
            return [row["priority"] for row in conn.execute(sql, args).fetchall()]
