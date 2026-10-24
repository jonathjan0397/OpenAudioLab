"""Batch 5: LM dataset-prep enrich claims + fixed-prompt eval A/B (fakes)."""

from __future__ import annotations

import hashlib
import json
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
        self.use_lora = False
        self.active = None
        self.loaded = False
        self.status_override: dict | None = None

    def ensure_model(self, model=None):
        self.calls.append("ensure")

    def ensure_llm(self, lm_model_path=None):
        self.calls.append("ensure_llm")
        return {"llm_initialized": True}

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
        self.loaded = True
        self.active = name
        self.use_lora = True

    def unload_lora(self):
        self.calls.append("unload")
        self.loaded = False
        self.active = None

    def set_use_lora(self, value):
        self.use_lora = bool(value)
        return {"ok": True}

    def set_lora_scale(self, scale, adapter_name=None):
        self.calls.append(f"scale:{scale}")
        return {"ok": True}

    def lora_status(self):
        if self.status_override is not None:
            return dict(self.status_override)
        return {"lora_loaded": self.loaded, "use_lora": self.use_lora,
                "active_adapter": self.active, "lora_scale": 1.0}


def _worker(client, adapter):
    w = SimpleNamespace(db=client.app.state.db, storage=client.app.state.storage,
                        settings=client.app.state.settings, worker_id="w-b5",
                        adapter=adapter, gen_adapter=None)
    w._lease_beat = lambda *a: TrainingWorker._lease_beat(w, *a)
    w._lora_passes = lambda req: TrainingWorker._lora_passes(w, req)
    w._lora_pass_engage = lambda *a: TrainingWorker._lora_pass_engage(w, *a)
    w._inert_guard = lambda samples: TrainingWorker._inert_guard(w, samples)
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

        def __init__(self):
            self.payloads: list[dict] = []
            self._n = 0

        def build_payload(self, **kw):
            self.payloads.append(dict(kw))
            return dict(kw)

        def submit(self, payload):
            return SimpleNamespace(task_id="t-1")

        def poll(self, task_id):
            return "succeeded", [{"file": "/v1/audio?path=/x/1.mp3"}]

        def download(self, url):
            self._n += 1
            return ("audio-payload-%06d" % self._n).encode() * 60
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
    rv_dir = tmp_path / "review"
    client.app.state.settings.review_dir = str(rv_dir)
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
        assert modes == {"baseline", "c100", "c050"}
    for mode in ("baseline", "c100", "c050"):
        got = client.app.state.storage.get(f"ml/eval/{bundle_id}/{mode}-p1.mp3")
        assert got.body
    assert "load" in adapter.calls
    assert any(c.startswith("scale:") for c in adapter.calls)
    # local review landing zone
    dest = rv_dir / bundle_id
    assert (dest / "baseline-p1.mp3").is_file() and (dest / "c100-p1.mp3").is_file()
    assert (dest / "c050-p1.mp3").is_file()
    page = (dest / "index.html").read_text()
    assert "test caption" in page and "Candidate @ 1.00" in page
    assert "Candidate @ 0.50" in page and "Baseline (no adapter)" in page


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


def test_auto_label_status_unwraps_data_envelope() -> None:
    from app.training_acestep import AceStepTrainingAdapter

    class _T:
        def get_json(self, path):
            return {"data": {"task_id": "t", "status": "completed"}}
    assert AceStepTrainingAdapter(_T()).auto_label_status("t")["status"] == "completed"


def _voice_setup(client, tmp_path, *, kind="voice"):
    import hashlib

    from app.models import MlDataset, MlModelBundle, new_uuid

    body = b"lora-bytes"
    key = f"ml/adapters/att-voc-{next(_SEQ)}/model.safetensors"
    client.app.state.storage.put(key, body)
    ds = MlDataset(id=new_uuid(), name="voc-ds", kind=kind, frozen_sha256="f",
                   manifest_json={"entries": [
                       {"path": "/x/one.mp3", "sha256": "a", "caption": "Alabama - One",
                        "lyrics": "first trained lyric line\nsecond line"},
                       {"path": "/x/two.mp3", "sha256": "b", "caption": "Alabama - Two",
                        "lyrics": "another trained lyric"}]})
    bundle_id = new_uuid()
    with client.app.state.db.session() as session:
        session.add(ds)
        session.add(MlModelBundle(id=bundle_id, name="voc-b", version="v1", kind="adapter",
                                  base_model="ace-step-1.5-turbo", state="candidate",
                                  artifact_key=key,
                                  sha256=hashlib.sha256(body).hexdigest(),
                                  bundle_json={"dataset_id": ds.id}))
        session.commit()
    return bundle_id


def test_eval_voice_bundle_sings_by_default(client, tmp_path) -> None:
    import hashlib

    import app.training_worker as tw
    from app.models import MlEvaluation
    from app.orchestration import claim_attempt

    client.app.state.settings.train_workdir = str(tmp_path / "work")
    client.app.state.settings.review_dir = str(tmp_path / "review")
    bundle_id = _voice_setup(client, tmp_path)
    r = client.post(f"/api/v1/admin/model-lab/bundles/{bundle_id}/eval-samples",
                    json={"prompts": [{"name": "story", "caption": "country ballad"}]})
    job_id = r.json()["job_id"]
    _, att, lease = claim_attempt(client.app.state.db, job_id, "w-b5")
    adapter = _FakeTrainingAdapter({"samples": []})
    w = SimpleNamespace(db=client.app.state.db, storage=client.app.state.storage,
                        settings=client.app.state.settings,
                        adapter=adapter, gen_adapter=None)
    w._lease_beat = lambda *a: TrainingWorker._lease_beat(w, *a)
    w._external_pass = lambda *a, **k: TrainingWorker._external_pass(w, *a, **k)
    w._verify_one = lambda *a, **k: TrainingWorker._verify_one(w, *a, **k)
    w._lyrics_one = lambda *a, **k: TrainingWorker._lyrics_one(w, *a, **k)
    w._lora_passes = lambda req: TrainingWorker._lora_passes(w, req)
    w._lora_pass_engage = lambda *a: TrainingWorker._lora_pass_engage(w, *a)
    w._inert_guard = lambda samples: TrainingWorker._inert_guard(w, samples)
    gen = _fake_gen(None)
    w.gen_adapter = gen
    TrainingWorker._model_lab_eval(w, job_id, att, lease)
    vocal = [p for p in gen.payloads if p["music_description"] == "country ballad"]
    assert vocal and all(p["instrumental"] is False for p in vocal)
    assert vocal[0]["lyrics"] == "first trained lyric line\nsecond line"
    with client.app.state.db.session() as session:
        ev = session.query(MlEvaluation).filter(
            MlEvaluation.bundle_id == bundle_id).one()
        entry = ev.scores_json["samples"][0]
        assert entry["instrumental"] is False
        assert entry["lyrics_sha256"] == hashlib.sha256(
            "first trained lyric line\nsecond line".encode()).hexdigest()
        assert "first trained lyric" not in json.dumps(ev.scores_json)
    page = (tmp_path / "review" / bundle_id / "index.html").read_text()
    assert "lyrics sha" in page


def test_eval_style_bundle_stays_instrumental(client, tmp_path) -> None:
    import app.training_worker as tw  # noqa: F401
    from app.orchestration import claim_attempt

    client.app.state.settings.train_workdir = str(tmp_path / "work2")
    bundle_id = _voice_setup(client, tmp_path, kind="style")
    r = client.post(f"/api/v1/admin/model-lab/bundles/{bundle_id}/eval-samples",
                    json={"prompts": [{"name": "instr", "caption": "test"}]})
    job_id = r.json()["job_id"]
    _, att, lease = claim_attempt(client.app.state.db, job_id, "w-b5")
    adapter = _FakeTrainingAdapter({"samples": []})
    w = SimpleNamespace(db=client.app.state.db, storage=client.app.state.storage,
                        settings=client.app.state.settings,
                        adapter=adapter, gen_adapter=None)
    w._lease_beat = lambda *a: TrainingWorker._lease_beat(w, *a)
    w._external_pass = lambda *a, **k: TrainingWorker._external_pass(w, *a, **k)
    w._verify_one = lambda *a, **k: TrainingWorker._verify_one(w, *a, **k)
    w._lyrics_one = lambda *a, **k: TrainingWorker._lyrics_one(w, *a, **k)
    w._lora_passes = lambda req: TrainingWorker._lora_passes(w, req)
    w._lora_pass_engage = lambda *a: TrainingWorker._lora_pass_engage(w, *a)
    w._inert_guard = lambda samples: TrainingWorker._inert_guard(w, samples)
    gen = _fake_gen(None)
    w.gen_adapter = gen
    TrainingWorker._model_lab_eval(w, job_id, att, lease)
    assert gen.payloads and all(p["instrumental"] is True and p["lyrics"] is None
                                for p in gen.payloads)


def test_eval_inert_guard_fails_identical_candidates(client, tmp_path) -> None:
    import app.training_worker as tw
    from app.orchestration import claim_attempt

    client.app.state.settings.train_workdir = str(tmp_path / "work")
    body = b"lora-bytes"
    key = "ml/adapters/att-inert/model.safetensors"
    client.app.state.storage.put(key, body)
    from app.models import Job, MlEvaluation, MlModelBundle, new_uuid
    bundle_id = new_uuid()
    with client.app.state.db.session() as session:
        session.add(MlModelBundle(id=bundle_id, name="in-b", version="v1", kind="adapter",
                                  base_model="acestep-v15-turbo", state="candidate",
                                  artifact_key=key, sha256=hashlib.sha256(body).hexdigest(),
                                  bundle_json={}))
        session.commit()
    r = client.post(f"/api/v1/admin/model-lab/bundles/{bundle_id}/eval-samples",
                    json={"prompts": [{"name": "p1", "caption": "c", "instrumental": True}]})
    job_id = r.json()["job_id"]
    _, att, lease = claim_attempt(client.app.state.db, job_id, "w-b5")
    adapter = _FakeTrainingAdapter({"samples": []})
    w = SimpleNamespace(db=client.app.state.db, storage=client.app.state.storage,
                        settings=client.app.state.settings, adapter=adapter, gen_adapter=None)
    w._lease_beat = lambda *a: tw.TrainingWorker._lease_beat(w, *a)
    w._lora_passes = lambda req: tw.TrainingWorker._lora_passes(w, req)
    w._lora_pass_engage = lambda *a: tw.TrainingWorker._lora_pass_engage(w, *a)
    w._inert_guard = lambda samples: tw.TrainingWorker._inert_guard(w, samples)

    class _Same:
        last_error = ""

        def build_payload(self, **kw):
            return dict(kw)

        def submit(self, payload):
            return SimpleNamespace(task_id="t-1")

        def poll(self, task_id):
            return "succeeded", [{"file": "/v1/audio?path=/x"}]

        def download(self, url):
            return b"identical-audio" * 300

    w.gen_adapter = _Same()
    tw.TrainingWorker._model_lab_eval(w, job_id, att, lease)
    from sqlalchemy import select as _sel
    with client.app.state.db.session() as session:
        assert session.query(MlEvaluation).filter(
            MlEvaluation.bundle_id == bundle_id).count() == 0
        job = session.execute(_sel(Job).where(Job.id == job_id)).scalar_one()
        assert job.status == "failed" and job.error_code == "ADAPTER_INERT"


def test_eval_contamination_guard(client, tmp_path) -> None:
    import app.training_worker as tw
    from app.orchestration import claim_attempt

    client.app.state.settings.train_workdir = str(tmp_path / "work2")
    body = b"lora-bytes"
    key = "ml/adapters/att-cont/model.safetensors"
    client.app.state.storage.put(key, body)
    from app.models import Job, MlModelBundle, new_uuid
    bundle_id = new_uuid()
    with client.app.state.db.session() as session:
        session.add(MlModelBundle(id=bundle_id, name="ct-b", version="v1", kind="adapter",
                                  base_model="acestep-v15-turbo", state="candidate",
                                  artifact_key=key, sha256=hashlib.sha256(body).hexdigest(),
                                  bundle_json={}))
        session.commit()
    r = client.post(f"/api/v1/admin/model-lab/bundles/{bundle_id}/eval-samples",
                    json={"prompts": [{"name": "p1", "caption": "c", "instrumental": True}]})
    job_id = r.json()["job_id"]
    _, att, lease = claim_attempt(client.app.state.db, job_id, "w-b5")
    adapter = _FakeTrainingAdapter({"samples": []})
    adapter.status_override = {"lora_loaded": True, "use_lora": True,
                               "active_adapter": "someone-elses-adapter", "lora_scale": 1.0}
    w = SimpleNamespace(db=client.app.state.db, storage=client.app.state.storage,
                        settings=client.app.state.settings, adapter=adapter, gen_adapter=None)
    w._lease_beat = lambda *a: tw.TrainingWorker._lease_beat(w, *a)
    w._lora_passes = lambda req: tw.TrainingWorker._lora_passes(w, req)
    w._lora_pass_engage = lambda *a: tw.TrainingWorker._lora_pass_engage(w, *a)
    w._inert_guard = lambda samples: tw.TrainingWorker._inert_guard(w, samples)
    gen = _fake_gen(None)
    w.gen_adapter = gen
    tw.TrainingWorker._model_lab_eval(w, job_id, att, lease)
    from sqlalchemy import select as _sel
    with client.app.state.db.session() as session:
        job = session.execute(_sel(Job).where(Job.id == job_id)).scalar_one()
        assert job.status == "failed" and job.error_code == "LORA_CONTAMINATED"
