"""Password hashing, bearer tokens and permission checks."""
import base64
import hashlib
import hmac
import os

from .errors import AuthenticationError

HASH_ITERATIONS = 2000


def hash_password(password, salt=None):
    salt = salt or os.urandom(8).hex()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), HASH_ITERATIONS).hex()
    return f"{salt}${digest}"


def verify_password(password, stored):
    try:
        salt, expected = stored.split("$", 1)
    except ValueError:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), HASH_ITERATIONS).hex()
    return hmac.compare_digest(actual, expected)


def _sign(payload, secret):
    mac = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")


def issue_token(user_id, secret, ttl_seconds, now):
    expires = int(now.timestamp()) + ttl_seconds
    payload = f"{user_id}.{expires}"
    return f"{payload}.{_sign(payload, secret)}"


def verify_token(token, secret, now):
    """Return the user id encoded in a valid, unexpired token."""
    if not token or token.count(".") != 2:
        raise AuthenticationError("malformed token")
    user_part, expires_part, signature = token.split(".")
    payload = f"{user_part}.{expires_part}"
    if not hmac.compare_digest(signature, _sign(payload, secret)):
        raise AuthenticationError("invalid token signature")
    try:
        user_id = int(user_part)
        expires = int(expires_part)
    except ValueError as exc:
        raise AuthenticationError("malformed token") from exc
    if int(now.timestamp()) >= expires:
        raise AuthenticationError("token expired")
    return user_id


def parse_authorization_header(value):
    if not value:
        raise AuthenticationError("missing credentials")
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthenticationError("unsupported authorization scheme")
    return token.strip()


# --- permissions -----------------------------------------------------------

def can_edit_task(user, task):
    """Only the owner of a task or an admin may edit its fields."""
    return user.is_admin or task.owner_id == user.id


def can_delete_task(user, task):
    return user.is_admin or task.owner_id == user.id


def can_change_status(user, task):
    """The owner, the current assignee, or an admin may change the status."""
    if user.is_admin:
        return True
    return user.id in (task.owner_id, task.assignee_id)


def can_view_user_email(viewer, user):
    return viewer.is_admin or viewer.id == user.id
