from __future__ import annotations

from conftest import TOKEN_A

CREDS = ("admin", "3671A113a05786!")
BAD_CREDS = ("admin", "wrong-password")


def _seed_audio_asset(client, *, mime="audio/wav", role="mix_wav") -> str:
    from app.models import Asset, new_uuid, utcnow

    asset_id = new_uuid()
    with client.app.state.db.session() as session:
        session.add(
            Asset(
                id=asset_id,
                job_id="job-seed",
                owner_id="tok_someone",
                storage_key=f"owners/tok_someone/adapters/{asset_id}/mix.wav",
                role=role,
                mime=mime,
                bytes=1234,
                sha256="a" * 64,
                duration_seconds=30.0,
                created_at=utcnow(),
            )
        )
        session.commit()
    return asset_id


def test_lab_page_requires_basic_auth(client) -> None:
    response = client.get("/lab")
    assert response.status_code == 401
    assert "Basic" in (response.headers.get("WWW-Authenticate") or "")


def test_lab_page_with_credentials(client) -> None:
    response = client.get("/lab", auth=CREDS)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "OpenAudioLab" in response.text


def test_lab_page_wrong_password(client) -> None:
    response = client.get("/lab", auth=BAD_CREDS)
    assert response.status_code == 401


def test_lab_api_requires_auth(client) -> None:
    # A bearer token is not HTTP Basic; the harness must still reject it.
    response = client.get("/lab/api/artifacts", headers={"Authorization": TOKEN_A})
    assert response.status_code == 401


def test_lab_artifacts_empty(client) -> None:
    response = client.get("/lab/api/artifacts", auth=CREDS)
    assert response.status_code == 200
    assert response.json() == {"artifacts": []}


def test_lab_artifacts_lists_audio_with_content_url(client) -> None:
    asset_id = _seed_audio_asset(client)
    response = client.get("/lab/api/artifacts", auth=CREDS)
    assert response.status_code == 200
    items = response.json()["artifacts"]
    assert len(items) == 1
    assert items[0]["asset_id"] == asset_id
    assert items[0]["url"].startswith(f"/api/v1/artifacts/{asset_id}/content?token=")


def test_lab_generate_then_poll(client) -> None:
    response = client.post(
        "/lab/api/generate",
        auth=CREDS,
        json={"music_description": "test tone", "instrumental": True, "duration_seconds": 30},
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    assert job_id

    poll = client.get(f"/lab/api/jobs/{job_id}", auth=CREDS)
    assert poll.status_code == 200
    body = poll.json()
    assert body["job_id"] == job_id
    assert body["status"] == "queued"
    assert body["artifacts"] == []


def test_lab_generate_rejects_empty_description(client) -> None:
    response = client.post("/lab/api/generate", auth=CREDS, json={"music_description": ""})
    assert response.status_code == 422
