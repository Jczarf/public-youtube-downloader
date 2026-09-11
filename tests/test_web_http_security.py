from fastapi.testclient import TestClient

from web.app import app


client = TestClient(app)


def test_health_has_security_headers_and_minimal_body():
    response = client.get("/health", headers={"host": "localhost"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store"


def test_api_docs_are_disabled_by_default():
    assert client.get("/docs", headers={"host": "localhost"}).status_code == 404
    assert client.get("/openapi.json", headers={"host": "localhost"}).status_code == 404


def test_untrusted_host_is_rejected():
    response = client.get("/health", headers={"host": "attacker.invalid"})

    assert response.status_code == 400
