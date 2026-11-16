import pytest

from tracker import attachments as attachments_module
from tracker.cache import TTLCache


def test_connection_closed_after_error(case, app):
    db = app.container.db
    with pytest.raises(RuntimeError):
        with db.connection():
            raise RuntimeError(case["message"])
    assert db.open_connections == 0


def test_failed_transaction_releases_connection(case, client, alice, app):
    for _ in range(case["attempts"]):
        client.post("/users", {"username": "alice", "email": "other@example.com", "password": "password123"})
    assert app.container.db.open_connections == 0


def test_attachment_file_handle_closed(case, client, alice, make_task, monkeypatch):
    handles = []
    real_open = open

    def tracking_open(*args, **kwargs):
        handle = real_open(*args, **kwargs)
        handles.append(handle)
        return handle

    monkeypatch.setattr(attachments_module, "open", tracking_open, raising=False)
    task = make_task()
    client.post(f"/tasks/{task['id']}/attachments", {"filename": case["name"], "content": "x"}, headers=alice[1])
    assert handles and all(h.closed for h in handles)


def test_expired_cache_entries_removed(case, clock):
    cache = TTLCache(case["ttl"], clock)
    cache.set("task:1", "value")
    clock.advance(case["ttl"] + 1)
    assert cache.get("task:1") is None
    assert "task:1" not in cache._data
