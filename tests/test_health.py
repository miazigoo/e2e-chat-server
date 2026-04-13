from fastapi.testclient import TestClient


def test_healthcheck(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()

    assert data["ok"] is True
    assert "service" in data
    assert "env" in data
