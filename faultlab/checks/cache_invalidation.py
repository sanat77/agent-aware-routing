def test_get_after_patch_is_fresh(case, client, alice, make_task):
    task = make_task(title=case["before"])
    client.get(f"/tasks/{task['id']}", headers=alice[1])
    client.patch(f"/tasks/{task['id']}", {"title": case["after"]}, headers=alice[1])
    assert client.get(f"/tasks/{task['id']}", headers=alice[1]).json()["title"] == case["after"]


def test_get_after_status_change_is_fresh(case, client, alice, make_task):
    task = make_task(title=case["before"])
    client.get(f"/tasks/{task['id']}", headers=alice[1])
    client.post(f"/tasks/{task['id']}/status", {"status": case["status"]}, headers=alice[1])
    assert client.get(f"/tasks/{task['id']}", headers=alice[1]).json()["status"] == case["status"]


def test_get_after_delete_is_404(case, client, alice, make_task):
    task = make_task(title=case["before"])
    client.get(f"/tasks/{task['id']}", headers=alice[1])
    client.delete(f"/tasks/{task['id']}", headers=alice[1])
    assert client.get(f"/tasks/{task['id']}", headers=alice[1]).status == 404


def test_stats_refresh_after_create(case, client, alice, make_task):
    for i in range(case["n"]):
        make_task(title=f"c{i}")
    assert client.get("/tasks/stats", headers=alice[1]).json()["total"] == case["n"]
    make_task(title="one more")
    assert client.get("/tasks/stats", headers=alice[1]).json()["total"] == case["n"] + 1


def test_stats_refresh_after_status_change(case, client, alice, make_task):
    tasks = [make_task(title=f"c{i}") for i in range(case["n"])]
    assert client.get("/tasks/stats", headers=alice[1]).json()["by_status"]["closed"] == 0
    client.post(f"/tasks/{tasks[0]['id']}/status", {"status": "closed"}, headers=alice[1])
    assert client.get("/tasks/stats", headers=alice[1]).json()["by_status"]["closed"] == 1
