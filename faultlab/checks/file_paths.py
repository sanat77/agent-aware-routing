def _upload(client, headers, task_id, filename):
    return client.post(f"/tasks/{task_id}/attachments", {"filename": filename, "content": "data"}, headers=headers)


def test_windows_path_reduced_to_basename(case, client, alice, make_task):
    task = make_task()
    response = _upload(client, alice[1], task["id"], f"C:\\Users\\me\\{case['name']}")
    assert response.status == 201
    assert response.json()["filename"] == case["name"]


def test_hidden_filename_rejected(case, client, alice, make_task):
    task = make_task()
    assert _upload(client, alice[1], task["id"], case["hidden"]).status == 422


def test_spaces_replaced_with_underscores(case, client, alice, make_task):
    task = make_task()
    response = _upload(client, alice[1], task["id"], f"my notes {case['name']}")
    assert response.json()["filename"] == f"my_notes_{case['name']}"


def test_nested_path_reduced_to_basename(case, client, alice, make_task):
    task = make_task()
    response = _upload(client, alice[1], task["id"], f"reports/{case['folder']}/{case['name']}")
    assert response.status == 201
    assert response.json()["filename"] == case["name"]
    assert client.get(f"/tasks/{task['id']}/attachments", headers=alice[1]).json()["items"] == [case["name"]]
