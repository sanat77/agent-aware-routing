import pytest

from tracker.errors import ValidationError
from tracker.validation import validate_task_payload, validate_user_payload


def test_title_required():
    with pytest.raises(ValidationError):
        validate_task_payload({})


def test_title_too_long():
    with pytest.raises(ValidationError):
        validate_task_payload({"title": "x" * 121})


def test_priority_out_of_range():
    with pytest.raises(ValidationError):
        validate_task_payload({"title": "t", "priority": 9})


def test_tags_normalized():
    assert validate_task_payload({"title": "t", "tags": ["UI", "ui", " api "]})["tags"] == ["ui", "api"]


def test_unknown_field_rejected():
    with pytest.raises(ValidationError):
        validate_task_payload({"title": "t", "owner_id": 3})


def test_valid_user():
    data = validate_user_payload({"username": "carol_1", "email": "Carol@Example.com", "password": "longenough"})
    assert data["email"] == "carol@example.com"


def test_short_password_rejected():
    with pytest.raises(ValidationError):
        validate_user_payload({"username": "carol", "email": "c@example.com", "password": "short"})


def test_api_returns_422_for_invalid_payload(client, alice):
    response = client.post("/tasks", {"title": ""}, headers=alice[1])
    assert response.status == 422
    assert response.json()["error"]["code"] == "validation_error"
