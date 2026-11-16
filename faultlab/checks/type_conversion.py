def _titles(response):
    return [t["title"] for t in response.json()["items"]]


def test_boolean_query_is_case_insensitive(case, client, alice, make_task):
    make_task(title="late", due_at="2026-03-01T00:00:00Z")
    response = client.get("/tasks", headers=alice[1], query={"overdue": case["mixed_case_true"]})
    assert response.status == 200
    assert _titles(response) == ["late"]


def test_false_string_means_false(case, client, alice, make_task):
    make_task(title="late", due_at="2026-03-01T00:00:00Z")
    make_task(title="fine", due_at="2026-12-01T00:00:00Z")
    response = client.get("/tasks", headers=alice[1], query={"overdue": case["false_word"]})
    assert _titles(response) == ["fine"]


def test_fractional_priority_rejected(case, client, alice):
    assert client.post("/tasks", {"title": "t", "priority": case["fraction"]}, headers=alice[1]).status == 422


def test_boolean_priority_rejected(case, client, alice):
    assert client.post("/tasks", {"title": "t", "priority": case["bool_value"]}, headers=alice[1]).status == 422
