from datetime import timedelta

import pytest

from tracker.auth import issue_token, verify_token
from tracker.errors import AuthenticationError


def test_missing_token_is_401(client):
    assert client.get("/tasks").status == 401


def test_bad_scheme_is_401(client):
    assert client.get("/tasks", headers={"Authorization": "Basic abc"}).status == 401


def test_token_roundtrip(clock):
    token = issue_token(7, "s", 60, clock.now())
    assert verify_token(token, "s", clock.now()) == 7


def test_tampered_token_rejected(clock):
    token = issue_token(7, "s", 60, clock.now())
    with pytest.raises(AuthenticationError):
        verify_token(token.replace("7.", "8.", 1), "s", clock.now())


def test_expired_token_rejected(clock):
    token = issue_token(7, "s", 60, clock.now())
    with pytest.raises(AuthenticationError):
        verify_token(token, "s", clock.now() + timedelta(seconds=61))


def test_login_wrong_password(client, alice):
    assert client.post("/auth/login", {"username": "alice", "password": "nope"}).status == 401


def test_non_owner_cannot_edit(client, bob, make_task):
    task = make_task()
    assert client.patch(f"/tasks/{task['id']}", {"title": "hack"}, headers=bob[1]).status == 403


def test_admin_can_delete(client, admin, make_task):
    task = make_task()
    assert client.delete(f"/tasks/{task['id']}", headers=admin[1]).status == 204


def test_email_hidden_from_other_users(client, alice, bob):
    body = client.get(f"/users/{alice[0].id}", headers=bob[1]).json()
    assert "email" not in body
    assert client.get("/users/me", headers=alice[1]).json()["email"] == "alice@example.com"
