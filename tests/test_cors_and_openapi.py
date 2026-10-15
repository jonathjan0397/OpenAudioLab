from __future__ import annotations

from conftest import auth, submit_body

ALLOWED = "https://openaudiolab.io"
DISALLOWED = "https://evil.example"


def _preflight(client, origin: str):
    return client.options(
        "/api/v1/jobs",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization, content-type, idempotency-key",
        },
    )


def test_preflight_allowed_origin(client) -> None:
    response = _preflight(client, ALLOWED)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED


def test_preflight_disallowed_origin_has_no_allow_header(client) -> None:
    response = _preflight(client, DISALLOWED)
    assert "access-control-allow-origin" not in response.headers


def test_simple_request_allowed_origin_exposes_headers(client) -> None:
    submit = client.post(
        "/api/v1/jobs",
        json=submit_body(),
        headers=auth(**{"Idempotency-Key": "cors-1", "Origin": ALLOWED}),
    )
    assert submit.status_code == 202
    assert submit.headers["access-control-allow-origin"] == ALLOWED
    assert "Location" in submit.headers["access-control-expose-headers"]


def test_openapi_documents_contract_routes(client) -> None:
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    for route in (
        "/api/v1/health/live",
        "/api/v1/health/ready",
        "/api/v1/models",
        "/api/v1/models/{model_id}",
        "/api/v1/jobs",
        "/api/v1/jobs/{job_id}",
        "/api/v1/jobs/{job_id}/cancel",
        "/api/v1/jobs/{job_id}/retry",
        "/api/v1/jobs/{job_id}/artifacts",
        "/api/v1/jobs/{job_id}/events",
        "/api/v1/artifacts/{asset_id}/download-url",
    ):
        assert route in paths, route
