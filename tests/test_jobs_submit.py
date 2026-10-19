from __future__ import annotations

import hashlib

from conftest import submit_body

VALID = {"Authorization": "Bearer user-a-secret-token", "Idempotency-Key": "k1"}


def post(client, body, key="k1"):
    return client.post("/api/v1/jobs", json=body, headers={**VALID, "Idempotency-Key": key})


def test_valid_vocal_submit_returns_202_with_location(client) -> None:
    response = post(client, submit_body())
    assert response.status_code == 202
    assert response.headers["Location"].startswith("/api/v1/jobs/")
    body = response.json()
    assert body["status"] == "queued"
    assert body["model_id"] == "ace-step-1.5"
    assert body["model_revision"]
    assert body["status_url"].endswith(body["job_id"])
    assert body["events_url"] == f"{body['status_url']}/events"
    assert body["poll_after_seconds"] >= 1


def test_instrumental_without_lyrics_accepted(client) -> None:
    response = post(client, submit_body(instrumental=True, lyrics=None))
    assert response.status_code == 202


def test_instrumental_with_lyrics_rejected(client) -> None:
    response = post(client, submit_body(instrumental=True, lyrics="la la"))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "LYRICS_NOT_ALLOWED"


def test_vocal_without_lyrics_rejected(client) -> None:
    response = post(client, submit_body(lyrics=None))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "LYRICS_REQUIRED"


def test_vocal_whitespace_only_lyrics_rejected(client) -> None:
    response = post(client, submit_body(lyrics="   \n  "))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "LYRICS_REQUIRED"


def test_unknown_field_rejected(client) -> None:
    response = post(client, submit_body(unknown_field="x"))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_unknown_operation_rejected(client) -> None:
    response = post(client, submit_body(operation="audio.render"))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "OPERATION_UNSUPPORTED"


def test_unknown_model_rejected(client) -> None:
    response = post(client, submit_body(model_id="not-a-model"))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "MODEL_UNKNOWN"


def test_disabled_model_not_queued_as_ready(client) -> None:
    response = post(client, submit_body(model_id="heartmula"))
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "MODEL_UNAVAILABLE"


def test_unknown_control_returns_422(client) -> None:
    response = post(client, submit_body(controls={"vibes": "high"}))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CONTROL_UNSUPPORTED"


def test_missing_idempotency_key_rejected(client) -> None:
    response = client.post(
        "/api/v1/jobs",
        json=submit_body(),
        headers={"Authorization": "Bearer user-a-secret-token"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


def test_invalid_output_option_rejected(client) -> None:
    response = post(client, submit_body(outputs=["mix_flac"]))
    assert response.status_code == 422


def test_lyrics_preserved_verbatim_and_hashed(client) -> None:
    lyrics = "  Morning émoji 🎵\r\npine  \n\n"
    response = post(client, submit_body(lyrics=lyrics))
    assert response.status_code == 202
    job_id = response.json()["job_id"]

    detail = client.get(f"/api/v1/jobs/{job_id}", headers=VALID)
    assert detail.status_code == 200
    assert detail.json()["lyrics_sha256"] == hashlib.sha256(lyrics.encode("utf-8")).hexdigest()

    from app.db import Db
    from app.models import Job
    from sqlalchemy import select

    db = Db(client.app.state.settings.database_url)
    with db.session() as session:
        stored = session.execute(select(Job).where(Job.id == job_id)).scalar_one().lyrics
    assert stored == lyrics


def test_body_limit_returns_413(client) -> None:
    big = submit_body(music_description="x" * 2_000_000)
    response = post(client, big)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "BODY_TOO_LARGE"
