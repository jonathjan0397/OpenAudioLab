"""M9: feature framework endpoints + task-locked LLM routes."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models import ArtistProfile, Asset, utcnow


def _seed_owner(client, email: str, username: str) -> str:
    client.post("/api/v1/auth/logout")
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "username": username, "password": "super-secret-1"},
    )
    return "usr_" + response.json()["user"]["id"]


def _seed_asset(client, owner_id: str, title: str | None, shared: bool = True) -> str:
    asset_id = str(uuid.uuid4())
    key = f"owners/{owner_id}/jobs/j1/{asset_id}/mix_wav.wav"
    client.app.state.storage.put(key, b"RIFFfake")
    with client.app.state.db.session() as session:
        session.add(
            Asset(
                id=asset_id,
                owner_id=owner_id,
                job_id="j1",
                storage_key=key,
                role="mix_wav",
                mime="audio/wav",
                bytes=8,
                sha256="x",
                synthetic=False,
                title=title,
                shared=shared,
                finalized_at=utcnow(),
                expires_at=utcnow() + __import__("datetime").timedelta(days=7),
            )
        )
        session.commit()
    return asset_id


def test_search(client) -> None:
    owner = _seed_owner(client, "m9-search@example.com", "m9search")
    _seed_asset(client, owner, "Midnight Signal")
    _seed_asset(client, owner, "Golden Hour")
    with client.app.state.db.session() as session:
        session.add(ArtistProfile(owner_id=owner, name="Nova Wells", slug="nova-wells", sharing_policy="public"))
        session.commit()

    response = client.get("/api/v1/search?q=signal")
    assert response.status_code == 200
    body = response.json()
    assert [t["title"] for t in body["tracks"]] == ["Midnight Signal"]
    assert body["artists"] == []

    response = client.get("/api/v1/search?q=nova")
    assert response.json()["artists"] == [{"name": "Nova Wells", "slug": "nova-wells"}]


def test_notifications(client) -> None:
    _seed_owner(client, "m9-notif@example.com", "m9notif")
    response = client.get("/api/v1/notifications")
    assert response.status_code == 200
    assert response.json()["notifications"] == []
    assert response.json()["active_count"] == 0


def test_export_artifact(client) -> None:
    owner = _seed_owner(client, "m9-export@example.com", "m9export")
    asset_id = _seed_asset(client, owner, "Exportable")

    response = client.post(f"/api/v1/artifacts/{asset_id}/export", json={"format": "stems"})
    assert response.status_code == 202  # M13: stems now queue a real export job
    assert response.json()["format"] == "stems"

    response = client.post(f"/api/v1/artifacts/{asset_id}/export", json={"format": "mp3"})
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    with client.app.state.db.session() as session:
        from app.models import Job

        job = session.execute(select(Job).where(Job.id == body["job_id"])).scalar_one()
        assert job.operation == "audio.export"
        assert job.request_json["outputs"] == ["mix_mp3"]


def test_follow_artist(client) -> None:
    owner = _seed_owner(client, "m9-follow@example.com", "m9follow")
    other = _seed_owner(client, "m9-followed@example.com", "m9followed")
    with client.app.state.db.session() as session:
        session.add(ArtistProfile(owner_id=other, name="Lumi", slug="lumi", sharing_policy="public"))
        session.commit()

    response = client.post("/api/v1/public/artists/lumi/follow")
    assert response.status_code == 200
    assert response.json() == {"following": True, "follower_count": 1}

    response = client.post("/api/v1/public/artists/lumi/follow")  # idempotent
    assert response.json()["follower_count"] == 1

    response = client.delete("/api/v1/public/artists/lumi/follow")
    assert response.json() == {"following": False, "follower_count": 0}

    response = client.post("/api/v1/public/artists/missing/follow")
    assert response.status_code == 404


def test_llm_routes_task_locked(client) -> None:
    _seed_owner(client, "m9-llm@example.com", "m9llm")

    # Disabled by default.
    response = client.post("/api/v1/llm/lyrics", json={"prompt": "a summer drive"})
    assert response.status_code == 503

    class FakeLlm:
        def __init__(self) -> None:
            self.calls = []

        def chat(self, system, user, max_tokens=400, temperature=0.8):
            self.calls.append((system, user))
            return "[Verse]\nfake lyrics line"

    fake = FakeLlm()
    client.app.state.llm = fake
    try:
        response = client.post("/api/v1/llm/lyrics", json={"prompt": "a summer drive"})
        assert response.status_code == 200
        assert response.json()["text"] == "[Verse]\nfake lyrics line"

        response = client.post("/api/v1/llm/lyrics", json={"mode": "humanize", "lyrics": "old words here"})
        assert response.status_code == 200
        assert "Humanize" in fake.calls[-1][1]

        response = client.post("/api/v1/llm/lyrics", json={"mode": "humanize"})
        assert response.status_code == 422

        response = client.post("/api/v1/llm/style-prompt", json={"description": "rainy jazz night"})
        assert response.status_code == 200
        assert response.json()["style_prompt"] == "[Verse]\nfake lyrics line"

        response = client.post("/api/v1/llm/title", json={"prompt": "rainy jazz night", "lyrics": "streetlights hum"})
        assert response.status_code == 200
        assert response.json()["title"] == "[Verse]\nfake lyrics line"
        assert "Lyrics excerpt" in fake.calls[-1][1]

        response = client.post("/api/v1/llm/title", json={})
        assert response.status_code == 422
    finally:
        del client.app.state.llm


def test_public_track_detail(client) -> None:
    owner = _seed_owner(client, "m12-trk@example.com", "m12track")
    asset_id = _seed_asset(client, owner, "Shared Anthem")
    response = client.get(f"/api/v1/public/tracks/{asset_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Shared Anthem"
    assert body["creator"] == "m12track"
    assert body["url"].startswith(f"/api/v1/artifacts/{asset_id}/content?token=")

    private = _seed_asset(client, owner, "Private Cut", shared=False)
    assert client.get(f"/api/v1/public/tracks/{private}").status_code == 404
    assert client.get("/api/v1/public/tracks/nope").status_code == 404
