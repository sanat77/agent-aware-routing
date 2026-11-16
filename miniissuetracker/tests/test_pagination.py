from types import SimpleNamespace

import pytest

from tracker.errors import ValidationError
from tracker.pagination import PageRequest, page_metadata, parse_page_request

CONFIG = SimpleNamespace(default_page_size=20, max_page_size=100)


def test_offset_for_first_page():
    assert PageRequest(1, 10).offset == 0


def test_metadata_for_partial_last_page():
    meta = page_metadata(25, PageRequest(3, 10))
    assert meta["total_pages"] == 3
    assert meta["has_next"] is False
    assert meta["has_prev"] is True


def test_per_page_is_capped():
    assert parse_page_request({"per_page": "500"}, CONFIG).per_page == 100


def test_page_zero_rejected():
    with pytest.raises(ValidationError):
        parse_page_request({"page": "0"}, CONFIG)


def test_list_endpoint_paginates(client, alice, make_task):
    for i in range(5):
        make_task(title=f"t{i}")
    body = client.get("/tasks", headers=alice[1], query={"per_page": 2, "page": 2}).json()
    assert [t["title"] for t in body["items"]] == ["t2", "t3"]
    assert body["meta"]["total"] == 5
