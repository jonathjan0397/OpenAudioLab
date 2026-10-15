from __future__ import annotations

from conftest import TOKEN_A, TOKEN_B, auth, submit


def _job_id(client) -> str:
    return submit(client, key="own").json()["job_id"]


def test_other_owner_cannot_read(client) -> None:
    job_id = _job_id(client)
    assert client.get(f"/api/v1/jobs/{job_id}", headers=auth(TOKEN_B)).status_code == 404


def test_other_owner_cannot_enumerate(client) -> None:
    _job_id(client)
    page = client.get("/api/v1/jobs", headers=auth(TOKEN_B)).json()
    assert page["jobs"] == []


def test_other_owner_cannot_cancel_or_retry(client) -> None:
    job_id = _job_id(client)
    assert client.post(f"/api/v1/jobs/{job_id}/cancel", headers=auth(TOKEN_B)).status_code == 404
    assert client.post(f"/api/v1/jobs/{job_id}/retry", headers=auth(TOKEN_B)).status_code == 404


def test_other_owner_cannot_read_artifacts_or_events(client) -> None:
    job_id = _job_id(client)
    assert client.get(f"/api/v1/jobs/{job_id}/artifacts", headers=auth(TOKEN_B)).status_code == 404
    assert client.get(f"/api/v1/jobs/{job_id}/events", headers=auth(TOKEN_B)).status_code == 404


def test_cancel_queued_then_retry(client) -> None:
    job_id = _job_id(client)
    cancelled = client.post(f"/api/v1/jobs/{job_id}/cancel", headers=auth(TOKEN_A))
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["upstream_termination_supported"] is False

    again = client.post(f"/api/v1/jobs/{job_id}/cancel", headers=auth(TOKEN_A))
    assert again.status_code == 200
    assert again.json()["status"] == "cancelled"

    retried = client.post(f"/api/v1/jobs/{job_id}/retry", headers=auth(TOKEN_A))
    assert retried.status_code == 200
    assert retried.json()["status"] == "queued"
    assert retried.json()["attempt_number"] == 2

    queued_retry = client.post(f"/api/v1/jobs/{job_id}/retry", headers=auth(TOKEN_A))
    assert queued_retry.status_code == 409
    assert queued_retry.json()["error"]["code"] == "STATE_CONFLICT"


def test_cancelled_job_detail_status(client) -> None:
    job_id = _job_id(client)
    client.post(f"/api/v1/jobs/{job_id}/cancel", headers=auth(TOKEN_A))
    detail = client.get(f"/api/v1/jobs/{job_id}", headers=auth(TOKEN_A)).json()
    assert detail["status"] == "cancelled"
    assert detail["finished_at"] is not None


def test_events_returns_sse_resync(client) -> None:
    job_id = _job_id(client)
    response = client.get(f"/api/v1/jobs/{job_id}/events", headers=auth(TOKEN_A))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: resync" in response.text


def test_download_url_unknown_asset_404(client) -> None:
    response = client.post("/api/v1/artifacts/no-such-asset/download-url", headers=auth(TOKEN_A))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ASSET_NOT_FOUND"
