"""Configuration loading.

Precedence (highest first): explicit overrides, TRACKER_* environment variables,
JSON config file, built-in defaults. Invalid values fall back to the next source.
"""
import json
import os
from dataclasses import dataclass, fields

DEFAULTS = {
    "database_path": "tracker.db",
    "secret_key": "dev-secret-change-me",
    "default_page_size": 20,
    "max_page_size": 100,
    "token_ttl_seconds": 3600,
    "cache_ttl_seconds": 30,
    "default_priority": 3,
    "retry_attempts": 3,
    "attachments_dir": "attachments",
}


@dataclass(frozen=True)
class Config:
    database_path: str
    secret_key: str
    default_page_size: int
    max_page_size: int
    token_ttl_seconds: int
    cache_ttl_seconds: int
    default_priority: int
    retry_attempts: int
    attachments_dir: str


def _coerce(name, value):
    """Coerce a raw value to the type of the default. Returns None if invalid."""
    default = DEFAULTS[name]
    if isinstance(default, int):
        try:
            number = int(str(value).strip())
        except (TypeError, ValueError):
            return None
        return number if number > 0 else None
    if value is None:
        return None
    text = str(value)
    return text if text.strip() else None


def _read_file(path):
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load_config(overrides=None, env=None, config_file=None):
    env = os.environ if env is None else env
    overrides = overrides or {}
    file_values = _read_file(config_file or env.get("TRACKER_CONFIG_FILE"))
    resolved = {}
    for field in fields(Config):
        name = field.name
        value = None
        for source in (overrides.get(name), env.get("TRACKER_" + name.upper()), file_values.get(name)):
            if source is None:
                continue
            value = _coerce(name, source)
            if value is not None:
                break
        resolved[name] = value if value is not None else DEFAULTS[name]
    if resolved["default_page_size"] > resolved["max_page_size"]:
        resolved["default_page_size"] = resolved["max_page_size"]
    return Config(**resolved)
