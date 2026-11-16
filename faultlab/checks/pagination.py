from tracker.pagination import PageRequest, page_metadata


def _titles(response):
    return [t["title"] for t in response.json()["items"]]


def test_first_page_starts_at_first_item(case, client, alice, make_task):
    for i in range(case["n"]):
        make_task(title=f"item-{i:03d}")
    response = client.get("/tasks", headers=alice[1], query={"page": 1, "per_page": case["per_page"]})
    expected = [f"item-{i:03d}" for i in range(min(case["per_page"], case["n"]))]
    assert _titles(response) == expected


def test_last_partial_page_is_counted(case):
    total = case["full_pages"] * case["per_page"] + case["remainder"]
    meta = page_metadata(total, PageRequest(1, case["per_page"]))
    assert meta["total_pages"] == case["full_pages"] + 1


def test_no_next_page_on_last_page(case):
    total = case["full_pages"] * case["per_page"] + case["remainder"]
    last = case["full_pages"] + 1
    meta = page_metadata(total, PageRequest(last, case["per_page"]))
    assert meta["has_next"] is False
    assert meta["has_prev"] is (last > 1)


def test_per_page_above_default_is_honoured(case, client, alice, make_task):
    for i in range(case["big_per_page"] + 2):
        make_task(title=f"bulk-{i:03d}")
    body = client.get("/tasks", headers=alice[1], query={"per_page": case["big_per_page"]}).json()
    assert len(body["items"]) == case["big_per_page"]
    assert body["meta"]["per_page"] == case["big_per_page"]
