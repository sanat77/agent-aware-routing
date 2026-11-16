def _titles(response):
    return [t["title"] for t in response.json()["items"]]


def test_search_matches_anywhere_in_title(case, client, alice, make_task):
    make_task(title=f"Fix {case['word']} regression")
    make_task(title="Unrelated chore")
    response = client.get("/tasks", headers=alice[1], query={"q": case["query"]})
    assert _titles(response) == [f"Fix {case['word']} regression"]


def test_filter_by_several_statuses(case, client, alice, make_task):
    created = {}
    for status in ("open", "in_progress", "closed"):
        task = make_task(title=f"task-{status}")
        if status != "open":
            client.post(f"/tasks/{task['id']}/status", {"status": status}, headers=alice[1])
        created[status] = task["title"]
    response = client.get("/tasks", headers=alice[1], query={"status": ",".join(case["statuses"])})
    expected = [created[s] for s in ("open", "in_progress", "closed") if s in case["statuses"]]
    assert _titles(response) == expected


def test_filter_unassigned_tasks(case, client, alice, bob, make_task):
    make_task(title="assigned", assignee_id=bob[0].id)
    make_task(title="nobody")
    response = client.get("/tasks", headers=alice[1], query={"assignee_id": case["none_token"]})
    assert response.status == 200
    assert _titles(response) == ["nobody"]


def test_priority_min_is_inclusive(case, client, alice, make_task):
    for i, priority in enumerate(case["priorities"]):
        make_task(title=f"p{i}", priority=priority)
    response = client.get("/tasks", headers=alice[1], query={"priority_min": case["priority_min"]})
    expected = [f"p{i}" for i, p in enumerate(case["priorities"]) if p >= case["priority_min"]]
    assert _titles(response) == expected


def test_tag_filter_matches_whole_tag(case, client, alice, make_task):
    make_task(title="exact", tags=[case["tag"]])
    make_task(title="lookalike", tags=[case["container_tag"]])
    response = client.get("/tasks", headers=alice[1], query={"tag": case["tag"]})
    assert _titles(response) == ["exact"]
