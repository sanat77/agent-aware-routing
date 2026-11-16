def test_blank_description_stored_as_null(case, client, alice):
    response = client.post("/tasks", {"title": case["title"], "description": case["blank"]}, headers=alice[1])
    assert response.status == 201
    assert response.json()["description"] is None


def test_whitespace_only_title_rejected(case, client, alice):
    response = client.post("/tasks", {"title": case["ws_title"]}, headers=alice[1])
    assert response.status == 422


def test_null_tags_become_empty_list(case, client, alice):
    response = client.post("/tasks", {"title": case["title"], "tags": None}, headers=alice[1])
    assert response.status == 201
    assert response.json()["tags"] == []


def test_null_priority_rejected(case, client, alice):
    response = client.post("/tasks", {"title": case["title"], "priority": None}, headers=alice[1])
    assert response.status == 422
    assert response.json()["error"]["details"] == {"priority": "required"}
