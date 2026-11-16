"""SQLite persistence: schema, connections and transactions."""
import sqlite3
import threading
from contextlib import contextmanager

from .errors import TransientError

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    full_name TEXT,
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_number INTEGER NOT NULL UNIQUE,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL,
    priority INTEGER NOT NULL,
    owner_id INTEGER NOT NULL REFERENCES users(id),
    assignee_id INTEGER REFERENCES users(id),
    due_at TEXT,
    tags TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS idempotency_keys (
    key TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    fingerprint TEXT NOT NULL,
    status INTEGER NOT NULL,
    body TEXT NOT NULL,
    PRIMARY KEY (key, user_id)
);
"""


class Database:
    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        self.open_connections = 0
        with self.connection() as conn:
            conn.executescript(SCHEMA)

    def _connect(self):
        try:
            conn = sqlite3.connect(self.path, timeout=1.0, check_same_thread=False)
        except sqlite3.OperationalError as exc:
            raise TransientError(str(exc)) from exc
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        with self._lock:
            self.open_connections += 1
        return conn

    def _close(self, conn):
        conn.close()
        with self._lock:
            self.open_connections -= 1

    @contextmanager
    def connection(self):
        conn = self._connect()
        try:
            yield conn
        finally:
            self._close(conn)

    @contextmanager
    def transaction(self):
        conn = self._connect()
        try:
            conn.execute("BEGIN")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            self._close(conn)
