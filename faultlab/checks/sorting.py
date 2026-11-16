def _titles(response):
    return [t["title"] for t in response.json()["items"]]


def test_descending_sort(case, client, alice, make_task):
    for title, priority in zip(case["titles"], case["priorities"]):
        make_task(title=title, priority=priority)
    pairs = list(zip(case["titles"], case["priorities"]))
    expected = [t for t, _ in sorted(pairs, key=lambda tp: -tp[1])]
    assert _titles(client.get("/tasks", headers=alice[1], query={"sort": "-priority"})) == expected


def test_ties_broken_by_ascending_id(case, client, alice, make_task):
    for title in case["titles"]:
        make_task(title=title, priority=case["same_priority"])
    assert _titles(client.get("/tasks", headers=alice[1], query={"sort": "priority"})) == case["titles"]


def test_title_sort_ignores_case(case, client, alice, make_task):
    for title in case["mixed_titles"]:
        make_task(title=title)
    expected = sorted(case["mixed_titles"], key=str.lower)
    assert _titles(client.get("/tasks", headers=alice[1], query={"sort": "title"})) == expected


def test_tasks_without_due_date_sort_last(case, client, alice, make_task):
    for title, due in zip(case["titles"], case["due_dates"]):
        make_task(title=title, due_at=due)
    dated = sorted([(d, t) for t, d in zip(case["titles"], case["due_dates"]) if d])
    undated = [t for t, d in zip(case["titles"], case["due_dates"]) if not d]
    expected = [t for _, t in dated] + undated
    assert _titles(client.get("/tasks", headers=alice[1], query={"sort": "due_at"})) == expected
