def test_create_returns_201(case, client, alice):
    assert client.post("/tasks", {"title": case["title"]}, headers=alice[1]).status == 201


def test_delete_returns_204_without_body(case, client, alice, make_task):
    task = make_task(title=case["title"])
    response = client.delete(f"/tasks/{task['id']}", headers=alice[1])
    assert response.status == 204
    assert response.body is None


def test_register_returns_201(case, client):
    response = client.post("/users", {"username": case["username"], "email": f"{case['username']}@example.com",
                                      "password": "password123"})
    assert response.status == 201


def test_attachment_upload_returns_201(case, client, alice, make_task):
    task = make_task(title=case["title"])
    response = client.post(f"/tasks/{task['id']}/attachments", {"filename": "a.txt", "content": "x"},
                           headers=alice[1])
    assert response.status == 201


def test_validation_error_returns_422(case, client, alice):
    assert client.post("/tasks", {"title": case["title"], "priority": 99}, headers=alice[1]).status == 422


def test_forbidden_returns_403(case, client, alice, bob, make_task):
    task = make_task(title=case["title"])
    assert client.delete(f"/tasks/{task['id']}", headers=bob[1]).status == 403
