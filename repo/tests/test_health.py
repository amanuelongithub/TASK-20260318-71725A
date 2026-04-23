from fastapi.testclient import TestClient

from app.main import app


def test_health() -> None:
    client = TestClient(app)
    
    # 1. Plain HTTP access (REJECTED by hardened policy)
    response = client.get('/health')
    assert response.status_code == 403
    assert "HTTPS required" in response.json()["detail"]

    # 2. HTTPS-simulated access (Allowed)
    response = client.get('/health', headers={"X-Forwarded-Proto": "https"})
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
