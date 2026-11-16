from tracker.timeutil import format_datetime


def test_is_overdue_is_a_boolean(case, client, alice, make_task):
    late = make_task(title="late", due_at=case["past_due"])
    fine = make_task(title="fine", due_at=case["future_due"])
    assert client.get(f"/tasks/{late['id']}", headers=alice[1]).json()["is_overdue"] is True
    assert client.get(f"/tasks/{fine['id']}", headers=alice[1]).json()["is_overdue"] is False


def test_password_hash_never_serialized(case, client, alice):
    body = client.get("/users/me", headers=alice[1]).json()
    assert "password_hash" not in body
    assert body["username"] == "alice"


def test_tags_serialized_as_list(case, client, alice, make_task):
    task = make_task(title="tagged", tags=case["tags"])
    body = client.get(f"/tasks/{task['id']}", headers=alice[1]).json()
    assert body["tags"] == case["tags"]


def test_updated_at_changes_on_update(case, client, alice, clock, make_task):
    task = make_task(title="before")
    clock.advance(case["seconds"])
    body = client.patch(f"/tasks/{task['id']}", {"title": "after"}, headers=alice[1]).json()
    assert body["updated_at"] == format_datetime(clock.now())
    assert body["created_at"] == task["created_at"]


def test_assignee_serialized(case, client, alice, bob, make_task):
    task = make_task(title="handover", assignee_id=bob[0].id)
    assert client.get(f"/tasks/{task['id']}", headers=alice[1]).json()["assignee_id"] == bob[0].id
