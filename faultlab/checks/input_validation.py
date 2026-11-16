def test_email_requires_top_level_domain(case, client):
    response = client.post("/users", {"username": "carol", "email": case["email"], "password": "password123"})
    assert response.status == 422
    assert response.json()["error"]["details"]["email"] == "invalid"


def test_username_rejects_symbols(case, client):
    response = client.post("/users", {"username": case["username"], "email": "c@example.com",
                                      "password": "password123"})
    assert response.status == 422
    assert response.json()["error"]["details"]["username"] == "invalid"


def test_create_rejects_unknown_fields(case, client, alice):
    response = client.post("/tasks", {"title": "t", case["unknown_field"]: 1}, headers=alice[1])
    assert response.status == 422


def test_short_password_rejected(case, client):
    response = client.post("/users", {"username": "carol", "email": "c@example.com", "password": case["password"]})
    assert response.status == 422
    assert response.json()["error"]["details"]["password"] == "too_short"


def test_non_string_title_rejected(case, client, alice):
    response = client.post("/tasks", {"title": case["bad_title"]}, headers=alice[1])
    assert response.status == 422
