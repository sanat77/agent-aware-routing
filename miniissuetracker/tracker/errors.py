"""Error hierarchy. Every ApiError maps to an HTTP status code and a stable error code."""


class ApiError(Exception):
    status = 500
    code = "internal_error"

    def __init__(self, message="", details=None):
        super().__init__(message)
        self.message = message or self.code.replace("_", " ")
        self.details = details

    def to_dict(self):
        body = {"code": self.code, "message": self.message}
        if self.details:
            body["details"] = self.details
        return {"error": body}


class BadRequestError(ApiError):
    status = 400
    code = "bad_request"


class AuthenticationError(ApiError):
    status = 401
    code = "unauthenticated"


class PermissionDeniedError(ApiError):
    status = 403
    code = "forbidden"


class NotFoundError(ApiError):
    status = 404
    code = "not_found"


class MethodNotAllowedError(ApiError):
    status = 405
    code = "method_not_allowed"


class ConflictError(ApiError):
    status = 409
    code = "conflict"


class InvalidTransitionError(ConflictError):
    code = "invalid_transition"


class ValidationError(ApiError):
    status = 422
    code = "validation_error"


class TransientError(Exception):
    """A failure that is safe to retry (e.g. a locked database)."""
