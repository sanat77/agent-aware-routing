def test_create_task_returns_201_and_defaults(client, alice):
    response = client.post("/tasks", {"title": "  Write docs  "}, headers=alice[1])
    assert response.status == 201
    body = response.json()
    assert body["title"] == "Write docs"
    assert body["status"] == "open"
    assert body["priority"] == 3
    assert body["tags"] == []
    assert body["owner_id"] == alice[0].id
    assert body["ticket"] == "MIT-1"


def test_get_missing_task_is_404(client, alice):
    response = client.get("/tasks/999", headers=alice[1])
    assert response.status == 404
    assert response.json()["error"]["code"] == "not_found"


def test_update_task_fields(client, alice, make_task):
    task = make_task(title="Old")
    response = client.patch(f"/tasks/{task['id']}", {"title": "New", "priority": 5}, headers=alice[1])
    assert response.status == 200
    assert response.json()["title"] == "New"
    assert response.json()["priority"] == 5


def test_delete_task_returns_204(client, alice, make_task):
    task = make_task()
    response = client.delete(f"/tasks/{task['id']}", headers=alice[1])
    assert response.status == 204
    assert response.body is None
    assert client.get(f"/tasks/{task['id']}", headers=alice[1]).status == 404


def test_unknown_route_is_404(client, alice):
    assert client.get("/nope", headers=alice[1]).status == 404


def test_wrong_method_is_405(client, alice):
    assert client.request("PUT", "/tasks", headers=alice[1]).status == 405


def test_invalid_json_is_400(app, alice):
    from tracker.http import Request

    request = Request("POST", "/tasks", {}, dict(alice[1]), b"{not json")
    response = app.handle(request)
    assert response.status == 400


def test_ticket_numbers_increment(make_task):
    assert make_task()["ticket"] == "MIT-1"
    assert make_task()["ticket"] == "MIT-2"


def test_assignee_must_exist(client, alice):
    response = client.post("/tasks", {"title": "x", "assignee_id": 42}, headers=alice[1])
    assert response.status == 422
