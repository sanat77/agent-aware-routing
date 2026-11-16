"""REST API routes."""
from .convert import parse_int
from .errors import ValidationError
from .http import Response, Router

PUBLIC_ROUTES = {"register", "login", "health"}


def build_router(container):
    router = Router()
    users = container.user_service
    tasks = container.task_service
    attachments = container.attachments

    @router.route("GET", "/health")
    def health(request):
        return {"status": "ok"}

    @router.route("POST", "/users")
    def register(request):
        user = users.register(request.json())
        return Response(201, users.get_profile(user, user.id))

    @router.route("POST", "/auth/login")
    def login(request):
        body = request.json()
        return users.login(body.get("username"), body.get("password"))

    @router.route("GET", "/users/me")
    def me(request):
        return users.get_profile(request.user, request.user.id)

    @router.route("GET", "/users/<int:user_id>")
    def get_user(request, user_id):
        return users.get_profile(request.user, user_id)

    @router.route("GET", "/tasks")
    def list_tasks(request):
        return tasks.list_tasks(request.query)

    @router.route("POST", "/tasks")
    def create_task(request):
        status, body = tasks.create_task(request.user, request.json(), request.header("Idempotency-Key"))
        return Response(status, body)

    @router.route("GET", "/tasks/stats")
    def stats(request):
        owner = parse_int(request.query.get("owner_id"), name="owner_id")
        return tasks.stats(owner)

    @router.route("GET", "/tasks/<int:task_id>")
    def get_task(request, task_id):
        return tasks.get_task(task_id)

    @router.route("PATCH", "/tasks/<int:task_id>")
    def update_task(request, task_id):
        return tasks.update_task(request.user, task_id, request.json())

    @router.route("POST", "/tasks/<int:task_id>/status")
    def change_status(request, task_id):
        body = request.json()
        if "status" not in body:
            raise ValidationError("status is required", {"status": "required"})
        return tasks.change_status(request.user, task_id, body["status"])

    @router.route("DELETE", "/tasks/<int:task_id>")
    def delete_task(request, task_id):
        tasks.delete_task(request.user, task_id)
        return Response(204, None)

    @router.route("POST", "/tasks/<int:task_id>/attachments")
    def add_attachment(request, task_id):
        tasks.get_task(task_id)
        body = request.json()
        content = body.get("content")
        if not isinstance(content, str):
            raise ValidationError("content must be a string", {"content": "invalid"})
        name = attachments.save(task_id, body.get("filename"), content)
        return Response(201, {"filename": name, "size": len(content)})

    @router.route("GET", "/tasks/<int:task_id>/attachments")
    def list_attachments(request, task_id):
        tasks.get_task(task_id)
        return {"items": attachments.list(task_id)}

    return router


def make_auth_hook(user_service):
    def before_request(request, handler):
        if handler.__name__ in PUBLIC_ROUTES:
            return
        request.user = user_service.authenticate(request.header("Authorization"))
    return before_request
