import pytest

from tracker.errors import ValidationError
from tracker.query import parse_sort


def titles(response):
    return [t["title"] for t in response.json()["items"]]


def test_parse_sort_default():
    assert parse_sort(None) == [("id", "ASC")]


def test_parse_sort_descending_with_tiebreak():
    assert parse_sort("-priority") == [("priority", "DESC"), ("id", "ASC")]


def test_parse_sort_rejects_unknown_field():
    with pytest.raises(ValidationError):
        parse_sort("password_hash")


def test_filter_by_status(client, alice, make_task):
    a = make_task(title="a")
    make_task(title="b")
    client.post(f"/tasks/{a['id']}/status", {"status": "in_progress"}, headers=alice[1])
    assert titles(client.get("/tasks", headers=alice[1], query={"status": "in_progress"})) == ["a"]


def test_search_is_case_insensitive(client, alice, make_task):
    make_task(title="Fix Login")
    make_task(title="Other")
    assert titles(client.get("/tasks", headers=alice[1], query={"q": "login"})) == ["Fix Login"]


def test_sort_by_priority_desc(client, alice, make_task):
    make_task(title="low", priority=1)
    make_task(title="high", priority=5)
    make_task(title="mid", priority=3)
    assert titles(client.get("/tasks", headers=alice[1], query={"sort": "-priority"})) == ["high", "mid", "low"]
