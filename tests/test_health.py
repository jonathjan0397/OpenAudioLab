from __future__ import annotations


def test_live_is_public(client) -> None:
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "live"}


def test_ready_is_public_and_ok(client) -> None:
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_root_health_alias_for_containers(client) -> None:
    assert client.get("/health/live").status_code == 200


def test_request_id_header_present(client) -> None:
    response = client.get("/api/v1/health/live")
    assert response.headers.get("X-Request-ID")
