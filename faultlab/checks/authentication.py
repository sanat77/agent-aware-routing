from datetime import timedelta

import pytest

from tracker.auth import issue_token, verify_token
from tracker.errors import AuthenticationError


def test_token_rejected_at_exact_expiry(case, clock):
    token = issue_token(case["user_id"], "secret", case["ttl"], clock.now())
    with pytest.raises(AuthenticationError):
        verify_token(token, "secret", clock.now() + timedelta(seconds=case["ttl"]))


def test_token_expires_after_ttl(case, client, alice, clock):
    clock.advance(3600 + case["extra"])
    assert client.get("/tasks", headers=alice[1]).status == 401


def test_bearer_scheme_is_case_insensitive(case, client, alice):
    token = alice[1]["Authorization"].split(" ", 1)[1]
    response = client.get("/tasks", headers={"Authorization": f"{case['scheme']} {token}"})
    assert response.status == 200


def test_wrong_password_rejected(case, client, alice):
    response = client.post("/auth/login", {"username": "alice", "password": case["wrong_password"]})
    assert response.status == 401
