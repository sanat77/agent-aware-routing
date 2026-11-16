def _move(client, headers, task_id, *statuses):
    response = None
    for status in statuses:
        response = client.post(f"/tasks/{task_id}/status", {"status": status}, headers=headers)
    return response


def test_blocked_task_cannot_be_finished(case, client, alice, make_task):
    task = make_task(title=case["title"])
    assert _move(client, alice[1], task["id"], "in_progress", "blocked").status == 200
    assert _move(client, alice[1], task["id"], "done").status == 409


def test_closed_task_is_final(case, client, alice, make_task):
    task = make_task(title=case["title"])
    assert _move(client, alice[1], task["id"], "closed").status == 200
    assert _move(client, alice[1], task["id"], case["reopen_to"]).status == 409


def test_done_task_can_be_reopened(case, client, alice, make_task):
    task = make_task(title=case["title"])
    assert _move(client, alice[1], task["id"], "in_progress", "done").status == 200
    response = _move(client, alice[1], task["id"], "open")
    assert response.status == 200
    assert response.json()["status"] == "open"


def test_in_progress_task_can_be_blocked(case, client, alice, make_task):
    task = make_task(title=case["title"])
    response = _move(client, alice[1], task["id"], "in_progress", "blocked")
    assert response.status == 200
    assert response.json()["status"] == "blocked"


def test_open_task_can_be_closed(case, client, alice, make_task):
    task = make_task(title=case["title"])
    response = _move(client, alice[1], task["id"], "closed")
    assert response.status == 200
    assert response.json()["status"] == "closed"
