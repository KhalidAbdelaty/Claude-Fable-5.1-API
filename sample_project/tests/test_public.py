def test_status_ok(client):
    assert client.get("/api/status").status_code == 200


def test_search_requires_query(client):
    assert client.get("/api/search").status_code == 400


def test_search_returns_empty_list(client):
    response = client.get("/api/search?q=python")
    assert response.status_code == 200
    assert response.get_json()["results"] == []


def test_feedback_requires_message(client):
    assert client.post("/api/feedback", json={}).status_code == 400


def test_feedback_accepts_message(client):
    response = client.post("/api/feedback", json={"message": "nice app"})
    assert response.status_code == 201
