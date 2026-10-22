"""Batch 5: LM dataset-prep enrich claims + fixed-prompt eval A/B (fakes)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.orchestration import claim_attempt
from app.training_worker import TrainingWorker

_SEQ = iter(range(1, 10000))


@pytest.fixture(autouse=True)
def _admin_session(client):
    from app.models import User

    client.post("/api/v1/auth/logout")
    resp = client.post("/api/v1/auth/register",
                       json={"email": f"b5{next(_SEQ)}@example.com",
                             "username": f"b5a{next(_SEQ)}", "password": "super-secret-1"})
    uid = resp.json()["user"]["id"]
    with client.app.state.db.session() as session:
        session.get(User, uid).role = "admin"
        session.commit()


class _FakeTrainingAdapter:
    def __init__(self, dataset_payload: dict) -> None:
        self.payload = dataset_payload
        self.calls: list[str] = []

    def ensure_model(self, model=None):
        self.calls.append("ensure")

    def scan_dataset(self, dir_, name, all_instrumental=False):
        self.calls.append("scan")
        assert all_instrumental is False

    def auto_label_async(self, *, save_path, **kw):
        Path(save_path).write_text(json.dumps(self.payload), encoding="utf-8")
        self.calls.append("auto_label")
        return {"task_id": "task-1"}

    def auto_label_status(self, task_id):
        self.calls.append("status")
        return {"status": "completed", "task_id": task_id}

    def load_lora(self, path, name=None):
        self.calls.append("load")

    def unload_lora(self):
        self.calls.append("unload")


def _worker(client, adapter):
    w = SimpleNamespace(db=client.app.state.db, storage=client.app.state.storage,
                        settings=client.app.state.settings, worker_id="w-b5",
                        adapter=adapter, gen_adapter=None)
    w._lease_beat = lambda *a: TrainingWorker._lease_beat(w, *a)
    return w


def _rec(client, tmp_path):
    from app.models import MlRecording, MlSource, new_uuid

    src = tmp_path / "Alabama - Mountain Music.mp3"
    src.write_bytes(b"audio-bytes")
    with client.app.state.db.session() as session:
        source = MlSource(id=new_uuid(), name=f"b5s-{next(_SEQ)}", status="approved")
        session.add(source)
        session.commit()
        rec = MlRecording(id=new_uuid(), source_id=source.id, path=str(src),
                          sha256="a1b2c3" + "0" * 58, duration_seconds=180.0,
                          artist="Alabama", title="Mountain Music",
                          review_status="approved")
        session.add(rec)
        session.commit()
        return rec.id


def test_enrich_creates_lm_claims_and_fills_missing_lyrics(client, tmp_path, monkeypatch) -> None:
    client.app.state.settings.train_workdir = str(tmp_path / "work")
    rid = _rec(client, tmp_path)
    adapter = _FakeTrainingAdapter({"samples": [{
        "filename": "a1b2c3-Alabama - Mountain Music.mp3",
        "caption": "90s country, warm male lead", "genre": "country", "bpm": 118,
        "lyrics": "lyric line one\nlyric line two", "formatted_lyrics": "",
    }]})
    r = client.post("/api/v1/admin/model-lab/enrich-selected",
                    json={"recording_ids": [rid]})
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    claim = claim_attempt(client.app.state.db, job_id, "w-b5")
    _, att, lease = claim
    w = _worker(client, adapter)
    TrainingWorker._model_lab_enrich(w, job_id, att, lease)

    from app.models import MlMetadataClaim, MlRecording
    with client.app.state.db.session() as session:
        rec = session.get(MlRecording, rid)
        claims = session.query(MlMetadataClaim).filter(
            MlMetadataClaim.recording_id == rid).all()
        assert {c.field for c in claims} >= {"caption_style", "genre", "bpm"}
        assert all(c.status == "suggested" and c.provenance == "acestep-lm" for c in claims)
        assert rec.lyrics_origin == "lm" and rec.lyrics_text.startswith("lyric line")
        assert rec.lyrics_sha256 == hashlib.sha256(rec.lyrics_text.encode()).hexdigest()
    assert "auto_label" in adapter.calls
    assert not (Path(client.app.state.settings.train_workdir)
                / f"ml-enrich-{job_id[:8]}").exists()  # scratch cleaned


def test_enrich_never_overwrites_existing_lyrics(client, tmp_path) -> None:
    client.app.state.settings.train_workdir = str(tmp_path / "work")
    rid = _rec(client, tmp_path)
    from app.models import MlRecording
    with client.app.state.db.session() as session:
        rec = session.get(MlRecording, rid)
        rec.lyrics_text = "human exact lyrics"
        rec.lyrics_sha256 = hashlib.sha256(b"human exact lyrics").hexdigest()
        rec.lyrics_origin = "submitted"
        session.commit()
    adapter = _FakeTrainingAdapter({"samples": [{
        "filename": "a1b2c3-Alabama - Mountain Music.mp3",
        "caption": "x", "lyrics": "LM should not replace", "formatted_lyrics": ""}]})
    r = client.post("/api/v1/admin/model-lab/enrich-selected", json={"recording_ids": [rid]})
    job_id = r.json()["job_id"]
    _, att, lease = claim_attempt(client.app.state.db, job_id, "w-b5")
    TrainingWorker._model_lab_enrich(_worker(client, adapter), job_id, att, lease)
    with client.app.state.db.session() as session:
        rec = session.get(MlRecording, rid)
        assert rec.lyrics_text == "human exact lyrics" and rec.lyrics_origin == "submitted"


def _fake_gen(storage_ref):
    class _Gen:
        last_error = ""

        def build_payload(self, **kw):
            return dict(kw)

        def submit(self, payload):
            return SimpleNamespace(task_id="t-1")

        def poll(self, task_id):
            return "succeeded", [{"file": "/v1/audio?path=/x/1.mp3"}]

        def download(self, url):
            return b"audio-payload" * 300
    return _Gen()


def test_eval_generates_ab_samples_and_evaluation_row(client, tmp_path) -> None:
    client.app.state.settings.train_workdir = str(tmp_path / "work")
    from app.models import MlEvaluation, MlModelBundle, new_uuid

    body = b"safetensors-fake-bytes"
    key = "ml/adapters/att-eval/model.safetensors"
    client.app.state.storage.put(key, body)
    bundle_id = new_uuid()
    with client.app.state.db.session() as session:
        session.add(MlModelBundle(id=bundle_id, name="eval-b", version="v1", kind="adapter",
                                  base_model="acestep-v15-turbo", state="candidate",
                                  artifact_key=key,
                                  sha256=hashlib.sha256(body).hexdigest(),
                                  bundle_json={}))
        session.commit()
    r = client.post(f"/api/v1/admin/model-lab/bundles/{bundle_id}/eval-samples",
                    json={"prompts": [{"name": "p1", "caption": "test caption"}]})
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    _, att, lease = claim_attempt(client.app.state.db, job_id, "w-b5")
    adapter = _FakeTrainingAdapter({"samples": []})
    w = _worker(client, adapter)
    w.gen_adapter = _fake_gen(None)
    TrainingWorker._model_lab_eval(w, job_id, att, lease)
    with client.app.state.db.session() as session:
        ev = session.query(MlEvaluation).filter(MlEvaluation.bundle_id == bundle_id).one()
        assert ev.kind == "ab" and ev.verdict is None
        modes = {s["mode"] for s in ev.scores_json["samples"]}
        assert modes == {"baseline", "candidate"}
    for mode in ("baseline", "candidate"):
        got = client.app.state.storage.get(f"ml/eval/{bundle_id}/{mode}-p1.mp3")
        assert got.body == b"audio-payload" * 300
    assert "load" in adapter.calls and "unload" in adapter.calls


def test_eval_rejects_tampered_artifact(client, tmp_path) -> None:
    client.app.state.settings.train_workdir = str(tmp_path / "work")
    from app.models import MlEvaluation, MlModelBundle, new_uuid

    key = "ml/adapters/att-tamper/model.safetensors"
    client.app.state.storage.put(key, b"real bytes")
    bundle_id = new_uuid()
    with client.app.state.db.session() as session:
        session.add(MlModelBundle(id=bundle_id, name="t", version="v1", kind="adapter",
                                  base_model="x", state="candidate", artifact_key=key,
                                  sha256="0" * 64, bundle_json={}))
        session.commit()
    r = client.post(f"/api/v1/admin/model-lab/bundles/{bundle_id}/eval-samples", json={})
    job_id = r.json()["job_id"]
    _, att, lease = claim_attempt(client.app.state.db, job_id, "w-b5")
    adapter = _FakeTrainingAdapter({"samples": []})
    TrainingWorker._model_lab_eval(_worker(client, adapter), job_id, att, lease)
    with client.app.state.db.session() as session:
        assert session.query(MlEvaluation).filter(
            MlEvaluation.bundle_id == bundle_id).count() == 0
