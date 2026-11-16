"""Application factory: wires configuration, persistence, services and HTTP routes."""
import os

from .api import build_router, make_auth_hook
from .attachments import AttachmentStore
from .cache import TTLCache
from .config import load_config
from .db import Database
from .http import Application, TestClient
from .idempotency import IdempotencyStore
from .repository import TaskRepository, UserRepository
from .sequence import TicketSequence
from .services import TaskService, UserService
from .timeutil import Clock


class Container:
    def __init__(self, config, clock):
        self.config = config
        self.clock = clock
        self.db = Database(config.database_path)
        self.users = UserRepository(self.db)
        self.tasks = TaskRepository(self.db)
        self.cache = TTLCache(config.cache_ttl_seconds, clock)
        self.sequence = TicketSequence()
        self.attachments = AttachmentStore(config.attachments_dir)
        self.idempotency = IdempotencyStore(self.db)
        self.user_service = UserService(self.users, config, clock)
        self.task_service = TaskService(
            self.tasks, self.users, config, clock, self.cache, self.idempotency, self.sequence
        )


def create_app(config=None, clock=None, overrides=None):
    config = config or load_config(overrides=overrides)
    clock = clock or Clock()
    container = Container(config, clock)
    router = build_router(container)
    app = Application(router, before_request=make_auth_hook(container.user_service))
    app.container = container
    app.test_client = lambda: TestClient(app)
    return app


def main():  # pragma: no cover - manual run helper
    from wsgiref.simple_server import make_server

    app = create_app()
    port = int(os.environ.get("PORT", "8000"))
    print(f"MiniIssueTracker listening on :{port}")
    make_server("127.0.0.1", port, app).serve_forever()


if __name__ == "__main__":  # pragma: no cover
    main()
