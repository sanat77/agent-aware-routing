import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tracker.app import create_app  # noqa: E402
from tracker.config import load_config  # noqa: E402
from tracker.timeutil import Clock  # noqa: E402

FIXED_NOW = datetime(2026, 3, 10, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def clock():
    return Clock(FIXED_NOW)


@pytest.fixture
def config(tmp_path):
    return load_config(
        overrides={"database_path": str(tmp_path / "test.db"), "attachments_dir": str(tmp_path / "files")},
        env={},
    )


@pytest.fixture
def app(config, clock):
    return create_app(config=config, clock=clock)


@pytest.fixture
def client(app):
    return app.test_client()


def _register(app, client, username, admin=False, full_name=None):
    payload = {"username": username, "email": f"{username}@example.com", "password": "password123"}
    if full_name:
        payload["full_name"] = full_name
    user = app.container.user_service.register(payload, is_admin=admin)
    token = client.post("/auth/login", {"username": username, "password": "password123"}).json()["token"]
    return user, {"Authorization": f"Bearer {token}"}


@pytest.fixture
def alice(app, client):
    return _register(app, client, "alice", full_name="Alice Liddell")


@pytest.fixture
def bob(app, client):
    return _register(app, client, "bob")


@pytest.fixture
def admin(app, client):
    return _register(app, client, "root", admin=True)


@pytest.fixture
def make_task(client, alice):
    def _make(headers=None, **fields):
        payload = {"title": fields.pop("title", "Task")}
        payload.update(fields)
        response = client.post("/tasks", payload, headers=headers or alice[1])
        assert response.status == 201, response.body
        return response.json()
    return _make
