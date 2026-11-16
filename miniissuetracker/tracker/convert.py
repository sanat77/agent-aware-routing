"""Type conversion helpers for query-string and JSON values."""
from .errors import ValidationError

TRUE_VALUES = {"true", "1", "yes", "on"}
FALSE_VALUES = {"false", "0", "no", "off"}


def parse_int(value, default=None, name="value"):
    """Convert a query/JSON value to int. None or '' returns `default`. Booleans are rejected."""
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        raise ValidationError(f"{name} must be an integer", {name: "not_an_integer"})
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        raise ValidationError(f"{name} must be an integer", {name: "not_an_integer"})
    try:
        return int(str(value).strip())
    except ValueError as exc:
        raise ValidationError(f"{name} must be an integer", {name: "not_an_integer"}) from exc


def parse_bool(value, default=None, name="value"):
    """Convert 'true'/'false'/'1'/'0'/'yes'/'no' (case-insensitive) or a bool to bool."""
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in TRUE_VALUES:
        return True
    if text in FALSE_VALUES:
        return False
    raise ValidationError(f"{name} must be a boolean", {name: "not_a_boolean"})


def parse_id_list(value, name="ids"):
    """Parse '1,2,3' into [1, 2, 3]."""
    if value is None or value == "":
        return []
    return [parse_int(part, name=name) for part in str(value).split(",") if part.strip()]
