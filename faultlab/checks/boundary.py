def test_title_at_max_length_accepted(case, client, alice):
    title = (case["prefix"] + "x" * 200)[:120]
    response = client.post("/tasks", {"title": title}, headers=alice[1])
    assert response.status == 201
    assert len(response.json()["title"]) == 120


def test_priority_upper_bound_accepted(case, client, alice):
    response = client.post("/tasks", {"title": case["prefix"], "priority": 5}, headers=alice[1])
    assert response.status == 201
    assert response.json()["priority"] == 5


def test_priority_lower_bound_accepted(case, client, alice):
    response = client.post("/tasks", {"title": case["prefix"], "priority": 1}, headers=alice[1])
    assert response.status == 201
    assert response.json()["priority"] == 1


def test_maximum_number_of_tags_accepted(case, client, alice):
    tags = [f"{case['tag_stem']}{i}" for i in range(10)]
    response = client.post("/tasks", {"title": case["prefix"], "tags": tags}, headers=alice[1])
    assert response.status == 201
    assert response.json()["tags"] == tags


def test_tag_at_max_length_accepted(case, client, alice):
    tag = (case["tag_stem"] * 30)[:30]
    response = client.post("/tasks", {"title": case["prefix"], "tags": [tag]}, headers=alice[1])
    assert response.status == 201
    assert response.json()["tags"] == [tag]


def test_values_past_the_limits_rejected(case, client, alice):
    assert client.post("/tasks", {"title": "x" * 121}, headers=alice[1]).status == 422
    assert client.post("/tasks", {"title": "t", "priority": 6}, headers=alice[1]).status == 422
    assert client.post("/tasks", {"title": "t", "priority": 0}, headers=alice[1]).status == 422
    eleven = [f"{case['tag_stem']}{i}" for i in range(11)]
    assert client.post("/tasks", {"title": "t", "tags": eleven}, headers=alice[1]).status == 422
