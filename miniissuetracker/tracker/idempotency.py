"""Idempotency-Key support so clients can safely retry POST requests."""
import hashlib
import json

from .errors import ConflictError


def fingerprint(payload):
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


class IdempotencyStore:
    def __init__(self, db):
        self.db = db

    def lookup(self, key, user_id, payload):
        """Return (status, body) of a previous identical request, or None.

        Re-using a key with a different payload is a client error (409).
        """
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT fingerprint, status, body FROM idempotency_keys WHERE key = ? AND user_id = ?",
                (key, user_id),
            ).fetchone()
        if row is None:
            return None
        if row["fingerprint"] != fingerprint(payload):
            raise ConflictError("Idempotency-Key reused with a different payload")
        return row["status"], json.loads(row["body"])

    def save(self, key, user_id, payload, status, body):
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO idempotency_keys (key, user_id, fingerprint, status, body)"
                " VALUES (?, ?, ?, ?, ?)",
                (key, user_id, fingerprint(payload), status, json.dumps(body)),
            )
