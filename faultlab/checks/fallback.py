import json

from tracker.config import load_config


def test_invalid_env_value_uses_default(case):
    config = load_config(env={"TRACKER_MAX_PAGE_SIZE": case["junk"]})
    assert config.max_page_size == 100


def test_non_positive_env_value_uses_default(case):
    config = load_config(env={"TRACKER_DEFAULT_PAGE_SIZE": str(case["non_positive"])})
    assert config.default_page_size == 20


def test_env_overrides_config_file(case, tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"default_page_size": case["file_value"]}))
    config = load_config(env={"TRACKER_DEFAULT_PAGE_SIZE": str(case["env_value"])}, config_file=str(path))
    assert config.default_page_size == case["env_value"]


def test_malformed_config_file_ignored(case, tmp_path):
    path = tmp_path / "config.json"
    path.write_text(case["broken_json"])
    config = load_config(env={}, config_file=str(path))
    assert config.default_page_size == 20


def test_display_name_falls_back_to_username(case, client, alice, bob):
    assert client.get("/users/me", headers=bob[1]).json()["display_name"] == "bob"
    assert client.get("/users/me", headers=alice[1]).json()["display_name"] == "Alice Liddell"
