from tracker.app import create_app
from tracker.config import load_config


def test_default_page_size_is_twenty(case, client, alice, make_task):
    assert load_config(env={}).default_page_size == 20
    for i in range(case["n"]):
        make_task(title=f"d{i}")
    body = client.get("/tasks", headers=alice[1]).json()
    assert len(body["items"]) == min(20, case["n"])
    assert body["meta"]["per_page"] == 20


def test_configured_default_priority_used(case, tmp_path, clock):
    config = load_config(overrides={"database_path": str(tmp_path / "p.db"),
                                    "default_priority": case["priority"]}, env={})
    app = create_app(config=config, clock=clock)
    user = app.container.user_service.register(
        {"username": "dora", "email": "dora@example.com", "password": "password123"})
    status, body = app.container.task_service.create_task(user, {"title": "prio"})
    assert status == 201
    assert body["priority"] == case["priority"]


def test_new_tasks_start_open(case, make_task):
    assert make_task(title=case["title"])["status"] == "open"


def test_token_valid_within_default_ttl(case, client, alice, clock):
    clock.advance(case["seconds"])
    assert client.get("/tasks", headers=alice[1]).status == 200
