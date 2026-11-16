def test_total_respects_filters(case, client, alice, make_task):
    for i in range(case["n"]):
        task = make_task(title=f"q{i}")
        if i < case["k"]:
            client.post(f"/tasks/{task['id']}/status", {"status": "in_progress"}, headers=alice[1])
    body = client.get("/tasks", headers=alice[1], query={"status": "in_progress"}).json()
    assert body["meta"]["total"] == case["k"]
    assert len(body["items"]) == case["k"]


def test_stats_for_owner(case, client, alice, bob, make_task):
    for i in range(case["k"]):
        make_task(title=f"a{i}")
    for i in range(case["n"]):
        make_task(headers=bob[1], title=f"b{i}", assignee_id=alice[0].id)
    body = client.get("/tasks/stats", headers=alice[1], query={"owner_id": alice[0].id}).json()
    assert body["total"] == case["k"]


def test_update_changes_only_target_task(case, client, alice, make_task):
    tasks = [make_task(title=f"keep{i}") for i in range(case["n"])]
    target = tasks[case["k"] % case["n"]]
    client.patch(f"/tasks/{target['id']}", {"title": "changed"}, headers=alice[1])
    titles = [client.get(f"/tasks/{t['id']}", headers=alice[1]).json()["title"] for t in tasks]
    assert titles == ["changed" if t["id"] == target["id"] else t["title"] for t in tasks]


def test_first_page_is_not_empty(case, client, alice, make_task):
    for i in range(case["n"]):
        make_task(title=f"r{i}")
    body = client.get("/tasks", headers=alice[1], query={"per_page": case["per_page"]}).json()
    assert len(body["items"]) == min(case["per_page"], case["n"])


def test_delete_removes_only_target(case, client, alice, make_task):
    tasks = [make_task(title=f"del{i}") for i in range(case["n"])]
    client.delete(f"/tasks/{tasks[case['k'] % case['n']]['id']}", headers=alice[1])
    assert client.get("/tasks", headers=alice[1]).json()["meta"]["total"] == case["n"] - 1
