"""Batch 2: worker-side dir_index, resumable scan jobs, DB-catalogued browse."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models import MlRecording
from app.orchestration import claim_attempt
from app.training_worker import TrainingWorker

_SEQ = iter(range(1, 10000))


@pytest.fixture(autouse=True)
def _admin_session(client):
    from app.models import User

    client.post("/api/v1/auth/logout")
    resp = client.post("/api/v1/auth/register",
                       json={"email": f"b2{next(_SEQ)}@example.com",
                             "username": f"b2a{next(_SEQ)}", "password": "super-secret-1"})
    uid = resp.json()["user"]["id"]
    with client.app.state.db.session() as session:
        session.get(User, uid).role = "admin"
        session.commit()


@pytest.fixture
def lib_root(client, tmp_path):
    root = tmp_path / "truenas"
    album = root / "Music Library" / "Alabama" / "Pass It On Down"
    album.mkdir(parents=True)
    (album / "01 Song One.mp3").write_bytes(b"fake-audio-one")
    (album / "01 Song One.lrc").write_text("[00:05.00]la la one", encoding="utf-8")
    (album / "album.nfo").write_text("<album><genre>Country</genre><year>1993</year></album>",
                                     encoding="utf-8")
    (album / "02 Song Two.mp3").write_bytes(b"fake-audio-two")
    original = client.app.state.settings.truenas_browse_root
    client.app.state.settings.truenas_browse_root = str(root)
    yield root
    client.app.state.settings.truenas_browse_root = original


def _run_worker_op(client, job_id, method_name):
    claim = claim_attempt(client.app.state.db, job_id, "w-b2")
    assert claim is not None
    _, att, lease = claim
    w = SimpleNamespace(db=client.app.state.db, storage=client.app.state.storage,
                        settings=client.app.state.settings)
    w._lease_beat = lambda *a: TrainingWorker._lease_beat(w, *a)
    getattr(TrainingWorker, method_name)(w, job_id, att, lease)


def test_rebuild_dir_index_counts_and_browse_from_index(client, lib_root) -> None:
    from app.model_lab import ModelLabError, browse_from_index, rebuild_dir_index

    stats = rebuild_dir_index(client.app.state.db, client.app.state.settings,
                              root=str(lib_root))
    assert stats["indexed"] >= 4 and stats["total_dirs"] >= 4
    album = lib_root / "Music Library" / "Alabama" / "Pass It On Down"
    with client.app.state.db.session() as session:
        body = browse_from_index(session, client.app.state.settings, str(album))
        names = {e["name"] for e in body["entries"] if not e["is_dir"]}
        assert names == {"01 Song One.mp3", "02 Song Two.mp3"}
        assert body["source"] == "dir_index"
        up = browse_from_index(session, client.app.state.settings,
                               str(lib_root / "Music Library" / "Alabama"))
        kids = [e for e in up["entries"] if e["is_dir"]]
        assert kids and kids[0]["n_audio"] == 2
        with pytest.raises(ModelLabError):
            browse_from_index(session, client.app.state.settings, str(lib_root / "ghost"))


def test_browse_falls_back_to_index_when_mount_gone(client, lib_root) -> None:
    from app.model_lab import rebuild_dir_index

    rebuild_dir_index(client.app.state.db, client.app.state.settings, root=str(lib_root))
    import shutil

    shutil.rmtree(lib_root)  # simulates the hub without the TrueNAS mount
    album = lib_root / "Music Library" / "Alabama" / "Pass It On Down"
    r = client.get(f"/api/v1/admin/model-lab/browse?path={album}")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "dir_index"
    assert {e["name"] for e in body["entries"]} == {"01 Song One.mp3", "02 Song Two.mp3"}


def test_scan_selected_directory_source(client, lib_root, monkeypatch) -> None:
    monkeypatch.setattr("app.library_parse.quick_decode_ok", lambda p, **k: True)
    album = lib_root / "Music Library" / "Alabama" / "Pass It On Down"
    r = client.post("/api/v1/admin/model-lab/scan-selected",
                    json={"source_name": f"dirsrc-{next(_SEQ)}", "roots": [str(album)]})
    assert r.status_code == 202
    sid, job_id = r.json()["sources"][0]["id"], r.json()["job_ids"][0]
    _run_worker_op(client, job_id, "_model_lab_scan")
    with client.app.state.db.session() as session:
        recs = session.query(MlRecording).filter(MlRecording.source_id == sid).all()
    assert len(recs) == 2
    by_name = {Path(x.path).name: x for x in recs}
    sidecar = by_name["01 Song One.mp3"]
    assert sidecar.lyrics_origin == "sidecar" and sidecar.lyrics_text
    assert sidecar.tags_state in ("parsed", "suspect") and sidecar.genre_raw == "Country"
    plain = by_name["02 Song Two.mp3"]
    assert not plain.lyrics_text
    batches = client.get("/api/v1/admin/model-lab/batches?state=completed").json()["batches"]
    assert any(b["source_id"] == sid and b["counts"].get("new") == 2 for b in batches)


def test_import_selected_and_resume(client, lib_root, monkeypatch) -> None:
    monkeypatch.setattr("app.library_parse.quick_decode_ok", lambda p, **k: True)
    album = lib_root / "Music Library" / "Alabama" / "Pass It On Down"
    paths = [str(album / "01 Song One.mp3"), str(album / "02 Song Two.mp3")]
    r = client.post("/api/v1/admin/model-lab/import-selected",
                    json={"source_name": f"res-{next(_SEQ)}", "paths": paths})
    assert r.status_code == 202
    job_id = r.json()["job_ids"][0]
    # first pass processes one chunk; simulate crash after partial commit
    _run_worker_op(client, job_id, "_model_lab_scan")
    with client.app.state.db.session() as session:
        sid = session.query(MlRecording).filter(
            MlRecording.path == paths[0]).one().source_id
        recs = session.query(MlRecording).filter(MlRecording.source_id == sid).count()
    assert recs == 2
    # re-run is idempotent: everything classifies as cached
    from app.model_lab import scan_source_resumable

    with client.app.state.db.session() as session:
        from app.models import MlImportBatch
        batch = session.query(MlImportBatch).filter(
            MlImportBatch.source_id == sid).one()
        batch.state = "running"  # pretend interrupted
        batch.cursor_json = {}   # resume from the beginning
        batch.counts_json = {}
        session.commit()
        batch_id = batch.id
    out = scan_source_resumable(client.app.state.db, sid, batch_id, chunk_files=1)
    assert out["state"] == "completed"
    assert out["counts"]["cached"] == 2 and out["counts"]["new"] == 0


def test_dirs_refresh_route(client, lib_root) -> None:
    r = client.post("/api/v1/admin/model-lab/dirs/refresh", json={})
    assert r.status_code == 202
    _run_worker_op(client, r.json()["job_id"], "_model_lab_dir_index")
    from app.models import MlDirIndex

    with client.app.state.db.session() as session:
        album = str(lib_root / "Music Library" / "Alabama" / "Pass It On Down")
        assert session.query(MlDirIndex).filter(MlDirIndex.path == album).count() == 1
