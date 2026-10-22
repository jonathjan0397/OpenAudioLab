"""TrueNAS browse + admin-selected import."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_SEQ = iter(range(1, 10000))


@pytest.fixture(autouse=True)
def _admin_session(client):
    from app.models import User

    client.post("/api/v1/auth/logout")
    email = f"tnas{next(_SEQ)}@example.com"
    resp = client.post("/api/v1/auth/register",
                       json={"email": email, "username": f"tn{next(_SEQ)}",
                             "password": "super-secret-1"})
    uid = resp.json()["user"]["id"]
    with client.app.state.db.session() as session:
        session.get(User, uid).role = "admin"
        session.commit()


@pytest.fixture
def tn_root(client, tmp_path):
    root = tmp_path / "truenas"
    (root / "AI Music" / "artist").mkdir(parents=True)
    (root / "notes.txt").write_text("not audio")
    wav = root / "AI Music" / "artist" / "track one.wav"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    str(wav)], capture_output=True, check=True)
    (root / "AI Music" / "artist" / "second.mp3").write_bytes(b"fake-mp3-bytes")
    original = client.app.state.settings.truenas_browse_root
    client.app.state.settings.truenas_browse_root = str(root)
    yield root
    client.app.state.settings.truenas_browse_root = original


def test_browse_lists_dirs_and_audio_only(client, tn_root) -> None:
    r = client.get("/api/v1/admin/model-lab/browse")
    assert r.status_code == 200
    body = r.json()
    assert body["path"] == str(tn_root) and body["parent"] is None
    names = [e["name"] for e in body["entries"]]
    assert "AI Music" in names and "notes.txt" not in names
    deep = client.get(f"/api/v1/admin/model-lab/browse?path={tn_root}/AI Music/artist")
    assert deep.status_code == 200
    files = {e["name"]: e for e in deep.json()["entries"]}
    assert set(files) == {"track one.wav", "second.mp3"}
    assert files["track one.wav"]["bytes"] > 0


def test_browse_guards(client, tn_root) -> None:
    escape = client.get("/api/v1/admin/model-lab/browse?path=/etc")
    assert escape.status_code == 422
    assert "BROWSE_OUT_OF_ROOT" in escape.json()["error"]["message"]
    tn_root_client = client.app.state.settings.truenas_browse_root
    client.app.state.settings.truenas_browse_root = ""
    off = client.get("/api/v1/admin/model-lab/browse")
    assert off.status_code == 503
    client.app.state.settings.truenas_browse_root = tn_root_client


def test_import_selected_queues_worker_scan(client, tn_root) -> None:
    wav = tn_root / "AI Music" / "artist" / "track one.wav"
    r = client.post("/api/v1/admin/model-lab/import-selected",
                    json={"source_name": f"pilot-{next(_SEQ)}", "paths": [str(wav)]})
    assert r.status_code == 202
    body = r.json()
    job_id, sid = body["job_ids"][0], body["sources"][0]["id"]

    from types import SimpleNamespace

    from app.models import MlRecording
    from app.orchestration import claim_attempt
    from app.training_worker import TrainingWorker
    from sqlalchemy import select

    claim = claim_attempt(client.app.state.db, job_id, "w-test")
    assert claim is not None
    _, att, lease = claim
    w = SimpleNamespace(db=client.app.state.db, storage=client.app.state.storage,
                        settings=client.app.state.settings)
    w._lease_beat = lambda *a: TrainingWorker._lease_beat(w, *a)
    TrainingWorker._model_lab_scan(w, job_id, att, lease)

    with client.app.state.db.session() as session:
        recs = session.execute(select(MlRecording)
                               .where(MlRecording.source_id == sid)).scalars().all()
    assert len(recs) == 1
    assert recs[0].duration_seconds and recs[0].duration_seconds > 0.5


def test_import_selected_validations(client, tn_root) -> None:
    dup_name = f"pilot-dup-{next(_SEQ)}"
    body = {"source_name": dup_name, "paths": [str(tn_root / "notes.txt")]}
    r = client.post("/api/v1/admin/model-lab/import-selected", json=body)
    assert r.status_code == 202 and len(r.json()["sources"]) == 1
    dup = client.post("/api/v1/admin/model-lab/import-selected", json=body)
    assert dup.status_code == 422
    outside = client.post("/api/v1/admin/model-lab/import-selected",
                          json={"source_name": f"x-{next(_SEQ)}", "paths": ["/etc/hosts"]})
    assert outside.status_code == 422
    empty = client.post("/api/v1/admin/model-lab/import-selected",
                        json={"source_name": f"x-{next(_SEQ)}", "paths": []})
    assert empty.status_code == 422
