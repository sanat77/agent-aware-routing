"""Config, retry, cache, attachments, conversion, time and database helpers."""
import pytest

from tracker.config import load_config
from tracker.convert import parse_bool, parse_int
from tracker.errors import TransientError, ValidationError
from tracker.retry import backoff_delays, retry_call
from tracker.timeutil import format_datetime, parse_datetime


def test_config_defaults():
    config = load_config(env={})
    assert config.default_page_size == 20
    assert config.max_page_size == 100


def test_config_env_override():
    assert load_config(env={"TRACKER_DEFAULT_PAGE_SIZE": "5"}).default_page_size == 5


def test_retry_succeeds_after_transient_failure():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 2:
            raise TransientError("locked")
        return "ok"

    assert retry_call(flaky, attempts=3, sleep=lambda s: None) == "ok"
    assert len(calls) == 2


def test_backoff_delays():
    assert backoff_delays(3, 0.1) == [0.1, 0.2]


def test_parse_int_and_bool():
    assert parse_int("7") == 7
    assert parse_bool("FALSE") is False
    with pytest.raises(ValidationError):
        parse_int("seven")


def test_parse_datetime_with_offset():
    assert format_datetime(parse_datetime("2026-01-01T10:00:00+02:00")) == "2026-01-01T08:00:00Z"


def test_attachment_roundtrip(client, alice, make_task):
    task = make_task()
    response = client.post(f"/tasks/{task['id']}/attachments", {"filename": "notes.txt", "content": "hi"},
                           headers=alice[1])
    assert response.status == 201
    assert client.get(f"/tasks/{task['id']}/attachments", headers=alice[1]).json()["items"] == ["notes.txt"]


def test_connections_are_closed(app, make_task):
    make_task()
    assert app.container.db.open_connections == 0


def test_cached_task_reflects_update(client, alice, make_task):
    task = make_task(title="before")
    client.get(f"/tasks/{task['id']}", headers=alice[1])
    client.patch(f"/tasks/{task['id']}", {"title": "after"}, headers=alice[1])
    assert client.get(f"/tasks/{task['id']}", headers=alice[1]).json()["title"] == "after"


def test_idempotent_create(client, alice):
    headers = dict(alice[1], **{"Idempotency-Key": "k1"})
    first = client.post("/tasks", {"title": "once"}, headers=headers)
    second = client.post("/tasks", {"title": "once"}, headers=headers)
    assert first.status == second.status == 201
    assert first.json()["id"] == second.json()["id"]
