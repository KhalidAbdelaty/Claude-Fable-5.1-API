def test_token_rejects_unknown_email(client):
    response = client.post("/api/auth/token", json={"email": "nobody@example.com", "password": "x"})
    assert response.status_code == 401


def test_token_rejects_empty_body(client):
    assert client.post("/api/auth/token", json={}).status_code == 401
