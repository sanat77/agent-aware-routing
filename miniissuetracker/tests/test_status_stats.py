from tracker.models import can_transition


def test_valid_transition():
    assert can_transition("open", "in_progress")


def test_closed_is_terminal():
    assert not can_transition("closed", "open")


def test_status_endpoint(client, alice, make_task):
    task = make_task()
    response = client.post(f"/tasks/{task['id']}/status", {"status": "in_progress"}, headers=alice[1])
    assert response.status == 200
    assert response.json()["status"] == "in_progress"


def test_invalid_transition_is_409(client, alice, make_task):
    task = make_task()
    response = client.post(f"/tasks/{task['id']}/status", {"status": "done"}, headers=alice[1])
    assert response.status == 409
    assert response.json()["error"]["code"] == "invalid_transition"


def test_stats_empty(client, alice):
    body = client.get("/tasks/stats", headers=alice[1]).json()
    assert body["total"] == 0
    assert body["completion_rate"] == 0.0
    assert body["average_priority"] is None


def test_stats_counts(client, alice, make_task):
    make_task(priority=1)
    make_task(priority=4)
    body = client.get("/tasks/stats", headers=alice[1]).json()
    assert body["total"] == 2
    assert body["by_status"]["open"] == 2
    assert body["average_priority"] == 2.5
