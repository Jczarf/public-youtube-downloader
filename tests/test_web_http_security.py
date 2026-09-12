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


def test_oversized_api_body_is_rejected_before_parsing():
    response = client.post(
        "/api/v1/resolve",
        content=b"x" * (20 * 1024),
        headers={
            "host": "localhost",
            "content-type": "application/json",
        },
    )

    assert response.status_code == 413


def test_cross_site_browser_api_request_is_rejected():
    response = client.post(
        "/api/v1/plan",
        json={
            "session_id": "not-a-real-session-token",
            "media_type": "video",
        },
        headers={
            "host": "localhost",
            "sec-fetch-site": "cross-site",
        },
    )

    assert response.status_code == 403


def test_unnecessary_http_method_is_rejected():
    response = client.request(
        "TRACE",
        "/health",
        headers={"host": "localhost"},
    )

    assert response.status_code == 405
    assert response.headers["allow"] == "GET, HEAD, POST"
