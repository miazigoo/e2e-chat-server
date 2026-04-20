from fastapi.testclient import TestClient


def test_health_live(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    body = response.json()

    assert body["ok"] is True
    assert body["data"]["ok"] is True
    assert "service" in body["data"]
    assert "env" in body["data"]
