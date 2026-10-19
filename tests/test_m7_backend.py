"""M7 backend: waveform peaks, timeseries, admin jobs list."""

from __future__ import annotations

import io
import json
import uuid
import wave

from fastapi.testclient import TestClient

from app.peaks import compute_peaks


def _make_wav(seconds: float = 0.25, rate: int = 8000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        frames = bytearray()
        for i in range(int(seconds * rate)):
            value = 12000 if (i // 200) % 2 == 0 else 3000
            frames += value.to_bytes(2, "little", signed=True)
        wav.writeframes(bytes(frames))
    return buf.getvalue()


def test_compute_peaks_shape() -> None:
    peaks = compute_peaks(_make_wav(), buckets=10)
    assert peaks["buckets"] > 0
    assert peaks["rate"] == 8000
    assert peaks["duration_seconds"] == 0.25
    assert len(peaks["peaks"]) == peaks["buckets"]
    assert all(0.0 <= p <= 1.0 for p in peaks["peaks"])
    assert max(peaks["peaks"]) > 0.2


def _seed_admin(client: TestClient, email: str = "m7-admin@example.com") -> None:
    from app.models import User, utcnow
    from app.auth import hash_password

    with client.app.state.db.session() as session:
        session.add(
            User(
                id=str(uuid.uuid4()),
                email=email,
                username="m7admin",
                password_hash=hash_password("super-secret-1"),
                role="admin",
                state="active",
                created_at=utcnow(),
            )
        )
        session.commit()
    client.post("/api/v1/auth/login", json={"email": email, "password": "super-secret-1"})


def test_timeseries_and_admin_jobs(client) -> None:
    _seed_admin(client)
    response = client.get("/api/v1/admin/stats/timeseries?days=7")
    assert response.status_code == 200
    body = response.json()
    assert body["days"] == 7
    assert len(body["series"]) == 7
    assert {"date", "completed", "failed", "cancelled", "active", "new_users"} <= set(body["series"][0])

    response = client.get("/api/v1/admin/jobs?limit=5")
    assert response.status_code == 200
    assert isinstance(response.json()["items"], list)


def test_waveform_endpoint(client) -> None:
    from app.models import Asset, utcnow

    _seed_admin(client, "m7-owner@example.com")
    client.post("/api/v1/auth/logout")
    client.post(
        "/api/v1/auth/register",
        json={"email": "m7-owner2@example.com", "username": "m7owner2", "password": "super-secret-1"},
    )
    asset_id = str(uuid.uuid4())
    key = f"owners/m7owner2/jobs/j1/a1/mix_wav.wav"
    payload = json.dumps({"buckets": 2, "rate": 8000, "duration_seconds": 0.25, "peaks": [0.5, 0.4]}).encode()
    client.app.state.storage.put(key[: -len(".wav")] + ".json", payload)
    with client.app.state.db.session() as session:
        session.add(
            Asset(
                id=asset_id,
                owner_id="usr_m7owner2",
                storage_key=key,
                role="mix_wav",
                mime="audio/wav",
                bytes=10,
                sha256="x",
                synthetic=False,
                finalized_at=utcnow(),
                expires_at=utcnow(),
            )
        )
        session.commit()

    # Not shared, wrong owner -> 403
    response = client.get(f"/api/v1/artifacts/{asset_id}/waveform")
    assert response.status_code == 403

    # Shared -> public 200
    with client.app.state.db.session() as session:
        asset = session.get(Asset, asset_id)
        asset.shared = True
        session.commit()
    response = client.get(f"/api/v1/artifacts/{asset_id}/waveform")
    assert response.status_code == 200
    assert response.json()["peaks"] == [0.5, 0.4]

    # Missing peaks -> 404
    missing = str(uuid.uuid4())
    with client.app.state.db.session() as session:
        session.add(
            Asset(
                id=missing,
                owner_id="usr_m7owner2",
                storage_key="owners/m7owner2/jobs/j2/a2/mix_wav.wav",
                role="mix_wav",
                mime="audio/wav",
                bytes=10,
                sha256="x",
                synthetic=False,
                finalized_at=utcnow(),
                shared=True,
            )
        )
        session.commit()
    response = client.get(f"/api/v1/artifacts/{missing}/waveform")
    assert response.status_code == 404


def test_waveform_fallback_computes_peaks(client) -> None:
    import io
    import wave as wavelib

    from app.models import Asset, utcnow

    _seed_admin(client, "m7-fb@example.com")
    client.post("/api/v1/auth/logout")
    client.post(
        "/api/v1/auth/register",
        json={"email": "m7-fb2@example.com", "username": "m7fb2", "password": "super-secret-1"},
    )
    asset_id = str(uuid.uuid4())
    key = "owners/m7fb2/jobs/j3/a3/mix_wav.wav"
    buf = io.BytesIO()
    with wavelib.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"".join(bytes([i % 256, (i * 7) % 256]) for i in range(4000)))
    client.app.state.storage.put(key, buf.getvalue())
    with client.app.state.db.session() as session:
        session.add(
            Asset(
                id=asset_id,
                owner_id="usr_m7fb2",
                storage_key=key,
                role="mix_wav",
                mime="audio/wav",
                bytes=len(buf.getvalue()),
                sha256="x",
                synthetic=False,
                finalized_at=utcnow(),
                shared=True,
            )
        )
        session.commit()

    response = client.get(f"/api/v1/artifacts/{asset_id}/waveform")
    assert response.status_code == 200
    body = response.json()
    assert body["buckets"] > 0
    assert len(body["peaks"]) == body["buckets"]
    # sidecar cached for next time
    cached = client.app.state.storage.get(key[: -len(".wav")] + ".json")
    assert json.loads(cached.body)["buckets"] == body["buckets"]
