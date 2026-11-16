def _with_key(headers, key):
    return dict(headers, **{"Idempotency-Key": key})


def test_idempotency_key_scoped_per_user(case, client, alice, bob):
    first = client.post("/tasks", {"title": case["title"]}, headers=_with_key(alice[1], case["key"]))
    second = client.post("/tasks", {"title": case["title"]}, headers=_with_key(bob[1], case["key"]))
    assert second.status == 201
    assert second.json()["id"] != first.json()["id"]
    assert second.json()["owner_id"] == bob[0].id


def test_key_reuse_with_different_payload_conflicts(case, client, alice):
    client.post("/tasks", {"title": case["title"]}, headers=_with_key(alice[1], case["key"]))
    response = client.post("/tasks", {"title": case["title"] + " v2"}, headers=_with_key(alice[1], case["key"]))
    assert response.status == 409


def test_retried_post_creates_single_task(case, client, alice):
    ids = set()
    for _ in range(case["repeats"]):
        ids.add(client.post("/tasks", {"title": case["title"]}, headers=_with_key(alice[1], case["key"])).json()["id"])
    assert len(ids) == 1
    assert client.get("/tasks", headers=alice[1]).json()["meta"]["total"] == 1


def test_field_order_does_not_matter(case, client, alice):
    headers = _with_key(alice[1], case["key"])
    first = client.post("/tasks", {"title": case["title"], "priority": case["priority"]}, headers=headers)
    second = client.post("/tasks", {"priority": case["priority"], "title": case["title"]}, headers=headers)
    assert second.status == 201
    assert second.json()["id"] == first.json()["id"]
