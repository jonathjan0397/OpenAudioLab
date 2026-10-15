from __future__ import annotations

import io
import zipfile

from sqlalchemy import select

from app.audio_worker import AudioWorker
from app.models import Asset, Job
from app.separator import NullSeparator
from app.worker import generate_fixture_wav
from conftest import TOKEN_A, TOKEN_B, auth, submit


class FakeSeparator:
    name = "fake-sep"

    def separate(self, wav_body: bytes) -> dict[str, bytes]:
        return {c: generate_fixture_wav(c, 1, 1) for c in ("drums", "bass", "other", "vocals")}


def _run_generation(client, orch, key="g1") -> str:
    response = submit(client, key=key)
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    orch.dispatcher.publish_once()
    orch.worker.run_once()
    return job_id


def _create_project(client, name="Song A", token=TOKEN_A) -> dict:
    response = client.post("/api/v1/projects", json={"name": name}, headers=auth(token))
    assert response.status_code == 201
    return response.json()


def _version_from_job(client, project_id: str, job_id: str, token=TOKEN_A) -> dict:
    response = client.post(
        f"/api/v1/projects/{project_id}/versions",
        json={"source_job_id": job_id, "label": "take 1"},
        headers=auth(token),
    )
    assert response.status_code == 201
    return response.json()


def _audio_worker(orch, separator=None) -> AudioWorker:
    return AudioWorker(
        orch.db, orch.queue, orch.storage, orch.settings,
        separator=separator if separator is not None else FakeSeparator(),
        worker_id="test-audio",
    )


def _export(client, version_id: str, outputs: list[str], key: str = "e1", token=TOKEN_A, **extra):
    body = {"source_version_id": version_id, "outputs": outputs, **extra}
    return client.post("/api/v1/exports", json=body, headers=auth(token, **{"Idempotency-Key": key}))


def _job_status(db, job_id: str) -> tuple[str, str | None]:
    with db.session() as session:
        job = session.execute(select(Job).where(Job.id == job_id)).scalar_one()
        return job.status, job.error_code


# --- projects -------------------------------------------------------------


def test_project_crud_and_etag(client) -> None:
    project = _create_project(client)
    assert project["etag"] == '"1"'
    project_id = project["project_id"]

    missing = client.patch(f"/api/v1/projects/{project_id}", json={"name": "B"}, headers=auth(TOKEN_A))
    assert missing.status_code == 428

    stale = client.patch(
        f"/api/v1/projects/{project_id}",
        json={"name": "B"},
        headers=auth(TOKEN_A, **{"If-Match": '"99"'}),
    )
    assert stale.status_code == 412
    assert stale.json()["error"]["code"] == "ETAG_MISMATCH"

    ok = client.patch(
        f"/api/v1/projects/{project_id}",
        json={"name": "B"},
        headers=auth(TOKEN_A, **{"If-Match": '"1"'}),
    )
    assert ok.status_code == 200
    assert ok.json()["name"] == "B"
    assert ok.json()["etag"] == '"2"'

    assert client.delete(f"/api/v1/projects/{project_id}", headers=auth(TOKEN_A)).status_code == 204
    assert client.get(f"/api/v1/projects/{project_id}", headers=auth(TOKEN_A)).status_code == 404


def test_project_ownership_isolation(client) -> None:
    project_id = _create_project(client)["project_id"]
    assert client.get(f"/api/v1/projects/{project_id}", headers=auth(TOKEN_B)).status_code == 404


# --- versions -------------------------------------------------------------


def test_version_from_job_and_restore(client, orch) -> None:
    job_id = _run_generation(client, orch)
    project_id = _create_project(client)["project_id"]
    version = _version_from_job(client, project_id, job_id)
    assert version["kind"] == "generated"
    assert version["manifest"]["model_revision"] == "1.5.0@ca1e85f"
    assert version["manifest"]["lyrics_sha256"]

    project = client.get(f"/api/v1/projects/{project_id}", headers=auth(TOKEN_A)).json()
    assert project["active_version_id"] == version["version_id"]

    restore = client.post(
        f"/api/v1/projects/{project_id}/restore",
        json={"version_id": version["version_id"]},
        headers=auth(TOKEN_A, **{"If-Match": project["etag"]}),
    )
    assert restore.status_code == 200
    assert restore.json()["active_version_id"] == version["version_id"]

    missing = client.post(
        f"/api/v1/projects/{project_id}/restore",
        json={"version_id": "nope"},
        headers=auth(TOKEN_A, **{"If-Match": restore.json()["etag"]}),
    )
    assert missing.status_code == 404


def test_version_requires_succeeded_job(client, orch) -> None:
    response = submit(client, key="pending-1")
    job_id = response.json()["job_id"]
    project_id = _create_project(client)["project_id"]
    conflict = client.post(
        f"/api/v1/projects/{project_id}/versions",
        json={"source_job_id": job_id},
        headers=auth(TOKEN_A),
    )
    assert conflict.status_code == 409


# --- uploads --------------------------------------------------------------


def _upload_wav(client, body: bytes, token=TOKEN_A, filename="song.wav") -> dict:
    session = client.post("/api/v1/assets/uploads", json={"filename": filename}, headers=auth(token))
    assert session.status_code == 201
    upload_id = session.json()["upload_id"]
    put = client.put(f"/api/v1/assets/uploads/{upload_id}/data", content=body, headers=auth(token))
    assert put.status_code == 200
    complete = client.post(f"/api/v1/assets/uploads/{upload_id}/complete", headers=auth(token))
    assert complete.status_code == 201
    return complete.json()["asset"]


def test_upload_flow_and_revoke(client) -> None:
    asset = _upload_wav(client, generate_fixture_wav("x", 1, 2))
    assert asset["kind"] == "uploaded"
    assert asset["sample_rate"] == 44100
    assert asset["mime"] == "audio/wav"

    fetched = client.get(f"/api/v1/assets/{asset['asset_id']}", headers=auth(TOKEN_A))
    assert fetched.status_code == 200
    assert client.delete(f"/api/v1/assets/{asset['asset_id']}", headers=auth(TOKEN_A)).status_code == 204
    assert client.get(f"/api/v1/assets/{asset['asset_id']}", headers=auth(TOKEN_A)).status_code == 410


def test_upload_garbage_fails_closed(client) -> None:
    session = client.post("/api/v1/assets/uploads", json={"filename": "x.bin"}, headers=auth(TOKEN_A))
    upload_id = session.json()["upload_id"]
    client.put(f"/api/v1/assets/uploads/{upload_id}/data", content=b"\x01\x02\x03\x04\x05", headers=auth(TOKEN_A))
    complete = client.post(f"/api/v1/assets/uploads/{upload_id}/complete", headers=auth(TOKEN_A))
    assert complete.status_code == 422
    assert complete.json()["error"]["code"] == "UPLOAD_NOT_AUDIO"


def test_upload_oversize_rejected(client, monkeypatch) -> None:
    session = client.post("/api/v1/assets/uploads", json={"filename": "big.wav"}, headers=auth(TOKEN_A))
    upload_id = session.json()["upload_id"]
    monkeypatch.setattr(client.app.state.settings, "max_upload_bytes", 10)
    put = client.put(f"/api/v1/assets/uploads/{upload_id}/data", content=b"0123456789ABCDEF", headers=auth(TOKEN_A))
    assert put.status_code == 413


def test_upload_cross_owner(client) -> None:
    session = client.post("/api/v1/assets/uploads", json={"filename": "a.wav"}, headers=auth(TOKEN_A))
    upload_id = session.json()["upload_id"]
    put = client.put(f"/api/v1/assets/uploads/{upload_id}/data", content=b"junk", headers=auth(TOKEN_B))
    assert put.status_code == 404


def test_version_from_uploaded_asset(client) -> None:
    asset = _upload_wav(client, generate_fixture_wav("y", 2, 1))
    project_id = _create_project(client)["project_id"]
    response = client.post(
        f"/api/v1/projects/{project_id}/versions",
        json={"source_asset_id": asset["asset_id"]},
        headers=auth(TOKEN_A),
    )
    assert response.status_code == 201
    assert response.json()["kind"] == "uploaded"


# --- exports --------------------------------------------------------------


def _version_for_export(client, orch) -> tuple[str, str]:
    job_id = _run_generation(client, orch)
    project_id = _create_project(client)["project_id"]
    version = _version_from_job(client, project_id, job_id)
    return project_id, version["version_id"]


def test_export_wav_and_mp3(client, orch) -> None:
    _, version_id = _version_for_export(client, orch)
    accepted = _export(client, version_id, ["mix_wav", "mix_mp3"], mp3={"bitrate_kbps": 320})
    assert accepted.status_code == 202
    job_id = accepted.json()["job_id"]
    assert accepted.json()["model_id"] == "audio-export"

    orch.dispatcher.publish_once()
    _audio_worker(orch).run_once()
    assert _job_status(orch.db, job_id)[0] == "succeeded"

    artifacts = client.get(f"/api/v1/jobs/{job_id}/artifacts", headers=auth(TOKEN_A)).json()["artifacts"]
    roles = {a["role"]: a for a in artifacts}
    assert set(roles) == {"mix_wav", "mix_mp3"}
    assert roles["mix_mp3"]["mime"] == "audio/mpeg"
    assert roles["mix_mp3"]["bytes"] > 0
    assert roles["mix_wav"]["processing"] == "native_copy"


def test_export_stems_and_zip(client, orch) -> None:
    _, version_id = _version_for_export(client, orch)
    accepted = _export(client, version_id, ["stems_wav", "stems_zip"], key="e-stems")
    job_id = accepted.json()["job_id"]
    orch.dispatcher.publish_once()
    _audio_worker(orch).run_once()
    assert _job_status(orch.db, job_id)[0] == "succeeded"

    artifacts = client.get(f"/api/v1/jobs/{job_id}/artifacts", headers=auth(TOKEN_A)).json()["artifacts"]
    stems = [a for a in artifacts if a["role"].startswith("stem_")]
    assert {a["stem_category"] for a in stems} == {"drums", "bass", "other", "vocals"}
    assert all(a["stem_source"] == "separated" for a in stems)
    zip_asset = next(a for a in artifacts if a["role"] == "stems_zip")

    url = client.post(f"/api/v1/artifacts/{zip_asset['asset_id']}/download-url", headers=auth(TOKEN_A)).json()["url"]
    body = client.get(url).content
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        names = set(archive.namelist())
    assert names == {"stems/drums.wav", "stems/bass.wav", "stems/other.wav", "stems/vocals.wav", "manifest.json"}


def test_export_separator_unavailable_fails_closed(client, orch) -> None:
    _, version_id = _version_for_export(client, orch)
    accepted = _export(client, version_id, ["stems_wav"], key="e-none")
    job_id = accepted.json()["job_id"]
    orch.dispatcher.publish_once()
    _audio_worker(orch, separator=NullSeparator()).run_once()
    status, code = _job_status(orch.db, job_id)
    assert status == "failed"
    assert code == "SEPARATOR_UNAVAILABLE"


def test_export_rejects_unsupported_settings(client, orch) -> None:
    _, version_id = _version_for_export(client, orch)
    bad_bitrate = _export(client, version_id, ["mix_mp3"], key="e-bad1", mp3={"bitrate_kbps": 200})
    assert bad_bitrate.status_code == 422

    bad_rate = _export(client, version_id, ["mix_wav"], key="e-bad2", wav={"sample_rate": 44100})
    assert bad_rate.status_code == 422
    assert bad_rate.json()["error"]["code"] == "EXPORT_SETTING_UNSUPPORTED"

    missing = _export(client, "no-such-version", ["mix_wav"], key="e-bad3")
    assert missing.status_code == 404


def test_export_idempotency(client, orch) -> None:
    _, version_id = _version_for_export(client, orch)
    first = _export(client, version_id, ["mix_wav"], key="e-idem")
    second = _export(client, version_id, ["mix_wav"], key="e-idem")
    assert second.json()["job_id"] == first.json()["job_id"]
    conflict = _export(client, version_id, ["mix_mp3"], key="e-idem")
    assert conflict.status_code == 409


def test_export_lineage_records_source_asset(client, orch) -> None:
    _, version_id = _version_for_export(client, orch)
    accepted = _export(client, version_id, ["mix_wav"], key="e-lineage")
    job_id = accepted.json()["job_id"]
    orch.dispatcher.publish_once()
    _audio_worker(orch).run_once()
    with orch.db.session() as session:
        asset = session.execute(select(Asset).where(Asset.job_id == job_id)).scalar_one()
        source_id = asset.source_asset_id
    assert source_id
    detail = client.get(f"/api/v1/assets/{source_id}", headers=auth(TOKEN_A))
    assert detail.status_code == 200
