def test_assignee_cannot_edit_fields(case, client, alice, bob, make_task):
    task = make_task(title=case["title"], assignee_id=bob[0].id)
    response = client.patch(f"/tasks/{task['id']}", {"title": case["new_title"]}, headers=bob[1])
    assert response.status == 403


def test_assignee_cannot_delete(case, client, alice, bob, make_task):
    task = make_task(title=case["title"], assignee_id=bob[0].id)
    assert client.delete(f"/tasks/{task['id']}", headers=bob[1]).status == 403


def test_assignee_can_change_status(case, client, alice, bob, make_task):
    task = make_task(title=case["title"], assignee_id=bob[0].id)
    response = client.post(f"/tasks/{task['id']}/status", {"status": case["status"]}, headers=bob[1])
    assert response.status == 200
    assert response.json()["status"] == case["status"]


def test_admin_can_see_user_email(case, client, alice, admin):
    body = client.get(f"/users/{alice[0].id}", headers=admin[1]).json()
    assert body["email"] == "alice@example.com"


def test_stranger_cannot_change_status(case, client, alice, bob, make_task):
    task = make_task(title=case["title"])
    response = client.post(f"/tasks/{task['id']}/status", {"status": case["status"]}, headers=bob[1])
    assert response.status == 403
