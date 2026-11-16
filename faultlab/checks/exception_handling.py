from tracker.auth import issue_token
from tracker.http import Request


def test_duplicate_registration_is_conflict(case, client, alice):
    response = client.post("/users", {"username": "alice", "email": case["email"], "password": "password123"})
    assert response.status == 409
    assert response.json()["error"]["code"] == "conflict"


def test_malformed_json_is_bad_request(case, app, alice):
    response = app.handle(Request("POST", "/tasks", {}, dict(alice[1]), case["bad_body"].encode()))
    assert response.status == 400


def test_token_for_unknown_user_is_unauthenticated(case, client, config, clock):
    token = issue_token(case["user_id"], config.secret_key, 60, clock.now())
    response = client.get("/tasks", headers={"Authorization": f"Bearer {token}"})
    assert response.status == 401


def test_invalid_due_date_is_validation_error(case, client, alice):
    response = client.post("/tasks", {"title": "x", "due_at": case["bad_date"]}, headers=alice[1])
    assert response.status == 422
