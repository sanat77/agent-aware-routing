from tracker.errors import ConflictError, NotFoundError


def test_error_body_has_code_and_message(case, client, alice):
    body = client.get(f"/tasks/{case['missing_id']}", headers=alice[1]).json()
    assert body["error"]["code"] == "not_found"
    assert str(case["missing_id"]) in body["error"]["message"]


def test_validation_details_returned(case, client, alice):
    response = client.post("/tasks", {"title": "x" * case["length"]}, headers=alice[1])
    assert response.status == 422
    assert response.json()["error"]["details"] == {"title": "too_long"}


def test_invalid_transition_is_conflict(case, client, alice, make_task):
    task = make_task()
    response = client.post(f"/tasks/{task['id']}/status", {"status": case["target"]}, headers=alice[1])
    assert response.status == 409
    assert response.json()["error"]["code"] == "invalid_transition"


def test_default_error_messages(case):
    assert NotFoundError().to_dict()["error"]["message"] == "not found"
    assert ConflictError().to_dict()["error"]["message"] == "conflict"
