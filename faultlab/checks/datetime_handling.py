from tracker.timeutil import format_datetime


def test_date_only_due_means_end_of_day(case, client, alice):
    response = client.post("/tasks", {"title": "dated", "due_at": case["date"]}, headers=alice[1])
    assert response.status == 201
    assert response.json()["due_at"] == f"{case['date']}T23:59:59Z"


def test_offset_converted_to_utc(case, client, alice):
    response = client.post("/tasks", {"title": "tz", "due_at": case["local"]}, headers=alice[1])
    assert response.status == 201
    assert response.json()["due_at"] == case["utc"]


def test_due_exactly_now_is_not_overdue(case, client, alice, clock):
    response = client.post("/tasks", {"title": "now", "due_at": format_datetime(clock.now())}, headers=alice[1])
    assert response.json()["is_overdue"] is False


def test_done_task_is_not_overdue(case, client, alice, make_task):
    task = make_task(title="finished", due_at=case["past_due"])
    for status in ("in_progress", "done"):
        response = client.post(f"/tasks/{task['id']}/status", {"status": status}, headers=alice[1])
    assert response.json()["status"] == "done"
    assert response.json()["is_overdue"] is False
