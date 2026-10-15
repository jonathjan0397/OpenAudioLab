from __future__ import annotations

from conftest import auth, submit_body


def test_missing_authorization_is_401(client) -> None:
    response = client.post("/api/v1/jobs", json=submit_body(), headers={"Idempotency-Key": "k1"})
    assert response.status_code == 401
    envelope = response.json()["error"]
    assert envelope["code"] == "UNAUTHENTICATED"
    assert envelope["request_id"]


def test_malformed_authorization_is_401(client) -> None:
    response = client.get("/api/v1/jobs", headers={"Authorization": "Token abc"})
    assert response.status_code == 401


def test_empty_bearer_is_401(client) -> None:
    response = client.get("/api/v1/jobs", headers=auth("Bearer "))
    assert response.status_code == 401


def test_body_user_id_field_does_not_grant_access(client) -> None:
    # Owner id comes only from the credential, never from a request field.
    response = client.post(
        "/api/v1/jobs",
        json=submit_body(),
        headers=auth("Bearer owner-x", **{"Idempotency-Key": "k1"}),
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    other = client.get(f"/api/v1/jobs/{job_id}", headers=auth("Bearer owner-y"))
    assert other.status_code == 404
