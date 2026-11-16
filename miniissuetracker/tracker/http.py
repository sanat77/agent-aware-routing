"""A minimal WSGI micro-framework: request parsing, routing, JSON responses, error mapping."""
import json
import re
from urllib.parse import parse_qsl

from .errors import ApiError, BadRequestError, MethodNotAllowedError, NotFoundError

STATUS_TEXT = {
    200: "OK", 201: "Created", 204: "No Content", 400: "Bad Request", 401: "Unauthorized",
    403: "Forbidden", 404: "Not Found", 405: "Method Not Allowed", 409: "Conflict",
    422: "Unprocessable Entity", 500: "Internal Server Error",
}


class Request:
    def __init__(self, method, path, query, headers, body_bytes):
        self.method = method.upper()
        self.path = path
        self.query = query
        self.headers = {k.lower(): v for k, v in headers.items()}
        self._body = body_bytes
        self.user = None

    def json(self):
        if not self._body:
            return {}
        try:
            return json.loads(self._body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BadRequestError("request body is not valid JSON") from exc

    def header(self, name, default=None):
        return self.headers.get(name.lower(), default)


class Response:
    def __init__(self, status=200, body=None, headers=None):
        self.status = status
        self.body = body
        self.headers = headers or {}

    def json(self):
        return self.body


class Router:
    _PARAM = re.compile(r"<(int:)?(\w+)>")

    def __init__(self):
        self.routes = []

    def add(self, method, pattern, handler):
        regex = "^" + self._PARAM.sub(
            lambda m: f"(?P<{m.group(2)}>\\d+)" if m.group(1) else f"(?P<{m.group(2)}>[^/]+)", pattern
        ) + "$"
        converters = {m.group(2): int for m in self._PARAM.finditer(pattern) if m.group(1)}
        self.routes.append((method.upper(), re.compile(regex), handler, converters))

    def route(self, method, pattern):
        def decorator(handler):
            self.add(method, pattern, handler)
            return handler
        return decorator

    def match(self, method, path):
        allowed = False
        for route_method, regex, handler, converters in self.routes:
            found = regex.match(path)
            if not found:
                continue
            allowed = True
            if route_method != method:
                continue
            params = {k: converters.get(k, str)(v) for k, v in found.groupdict().items()}
            return handler, params
        if allowed:
            raise MethodNotAllowedError(f"{method} not allowed on {path}")
        raise NotFoundError(f"no route for {path}")


def error_response(exc):
    return Response(exc.status, exc.to_dict())


class Application:
    def __init__(self, router, before_request=None, logger=None):
        self.router = router
        self.before_request = before_request
        self.logger = logger

    def handle(self, request):
        try:
            handler, params = self.router.match(request.method, request.path)
            if self.before_request:
                self.before_request(request, handler)
            result = handler(request, **params)
            if isinstance(result, Response):
                return result
            return Response(200, result)
        except ApiError as exc:
            return error_response(exc)
        except Exception as exc:  # noqa: BLE001 - last-resort guard
            if self.logger:
                self.logger(exc)
            return Response(500, {"error": {"code": "internal_error", "message": "internal server error"}})

    def __call__(self, environ, start_response):
        length = int(environ.get("CONTENT_LENGTH") or 0)
        body = environ["wsgi.input"].read(length) if length else b""
        headers = {k[5:].replace("_", "-"): v for k, v in environ.items() if k.startswith("HTTP_")}
        if environ.get("CONTENT_TYPE"):
            headers["Content-Type"] = environ["CONTENT_TYPE"]
        query = dict(parse_qsl(environ.get("QUERY_STRING", ""), keep_blank_values=True))
        response = self.handle(Request(environ["REQUEST_METHOD"], environ.get("PATH_INFO", "/"), query, headers, body))
        payload = b"" if response.body is None else json.dumps(response.body).encode()
        out_headers = [("Content-Type", "application/json")] + list(response.headers.items())
        start_response(f"{response.status} {STATUS_TEXT.get(response.status, '')}", out_headers)
        return [payload]


class TestClient:
    """In-process client used by the test-suite (no sockets)."""

    __test__ = False

    def __init__(self, app):
        self.app = app

    def request(self, method, path, json_body=None, headers=None, query=None):
        body = b"" if json_body is None else json.dumps(json_body).encode()
        request = Request(method, path, {k: str(v) for k, v in (query or {}).items()}, headers or {}, body)
        response = self.app.handle(request)
        # round-trip through JSON exactly like a real HTTP response would
        if response.body is not None:
            response.body = json.loads(json.dumps(response.body))
        return response

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, json_body=None, **kw):
        return self.request("POST", path, json_body=json_body, **kw)

    def patch(self, path, json_body=None, **kw):
        return self.request("PATCH", path, json_body=json_body, **kw)

    def delete(self, path, **kw):
        return self.request("DELETE", path, **kw)
