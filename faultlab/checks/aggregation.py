def _create(client, headers, make_task, statuses, priorities=None):
    paths = {
        "open": [],
        "in_progress": ["in_progress"],
        "blocked": ["in_progress", "blocked"],
        "done": ["in_progress", "done"],
        "closed": ["closed"],
    }
    for i, status in enumerate(statuses):
        priority = priorities[i] if priorities else 3
        task = make_task(title=f"s{i}", priority=priority)
        for step in paths[status]:
            client.post(f"/tasks/{task['id']}/status", {"status": step}, headers=headers)


def test_completion_rate_counts_closed_tasks(case, client, alice, make_task):
    _create(client, alice[1], make_task, case["statuses"])
    finished = sum(1 for s in case["statuses"] if s in ("done", "closed"))
    body = client.get("/tasks/stats", headers=alice[1]).json()
    assert body["completion_rate"] == round(finished / len(case["statuses"]), 4)


def test_average_priority_keeps_fraction(case, client, alice, make_task):
    _create(client, alice[1], make_task, ["open"] * len(case["priorities"]), case["priorities"])
    body = client.get("/tasks/stats", headers=alice[1]).json()
    assert body["average_priority"] == round(sum(case["priorities"]) / len(case["priorities"]), 2)


def test_open_count_includes_active_tasks(case, client, alice, make_task):
    _create(client, alice[1], make_task, case["statuses"])
    unfinished = sum(1 for s in case["statuses"] if s not in ("done", "closed"))
    assert client.get("/tasks/stats", headers=alice[1]).json()["open_count"] == unfinished


def test_completion_rate_has_four_decimals(case, client, alice, make_task):
    statuses = ["closed"] * case["k"] + ["open"] * (case["n"] - case["k"])
    _create(client, alice[1], make_task, statuses)
    assert client.get("/tasks/stats", headers=alice[1]).json()["completion_rate"] == round(case["k"] / case["n"], 4)


def test_stats_with_no_finished_tasks(case, client, alice, make_task):
    _create(client, alice[1], make_task, ["open"] * case["n"])
    response = client.get("/tasks/stats", headers=alice[1])
    assert response.status == 200
    body = response.json()
    assert body["by_status"] == {"open": case["n"], "in_progress": 0, "blocked": 0, "done": 0, "closed": 0}
    assert body["completion_rate"] == 0.0
