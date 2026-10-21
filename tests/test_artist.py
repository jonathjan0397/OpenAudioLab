"""UAIS artist voice tests: dataset QC, finalize, worker flows, resolver."""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select

from app.models import Job, VoiceAdapter, VoiceProfile
from app.training_worker import TrainingWorker
from app.worker import generate_fixture_wav
from conftest import TOKEN_A, TOKEN_B, auth


class FakeTrainAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.status = {
            "is_training": False, "error": None, "current_step": 42, "current_epoch": 3,
            "loss_history": [{"step": 42, "loss": 0.5}], "steps_per_second": 2.0,
        }

    def ensure_model(self, model=None):
        self.calls.append(("ensure_model",))
        return {}

    def scan_dataset(self, audio_dir, dataset_name, all_instrumental=False):
        self.calls.append(("scan", audio_dir, all_instrumental))
        return {"num_samples": 2}

    def preprocess(self, output_dir, skip_existing=False):
        self.calls.append(("preprocess", output_dir))
        return {"num_tensors": 2}

    def start_training(self, tensor_dir, lora_output_dir, epochs, seed, hyperparams=None):
        self.calls.append(("start", epochs, seed))
        return {}

    def training_status(self):
        return self.status

    def stop_training(self):
        self.calls.append(("stop",))
        return {}

    def export(self, lora_output_dir, export_path):
        self.calls.append(("export", export_path))
        Path(export_path).mkdir(parents=True, exist_ok=True)
        (Path(export_path) / "adapter_config.json").write_text("{}")
        (Path(export_path) / "adapter_model.safetensors").write_bytes(b"weights")
        return {"export_path": export_path}

    def load_lora(self, path, adapter_name=None):
        self.calls.append(("load", path))
        return {}

    def unload_lora(self):
        self.calls.append(("unload",))
        return {}

    def set_use_lora(self, use_lora):
        self.calls.append(("use_lora", use_lora))
        return {}


class FakeGenAdapter:
    def __init__(self) -> None:
        self.submitted = 0

    def build_payload(self, **kwargs):
        return kwargs

    def submit(self, payload):
        self.submitted += 1
        return SimpleNamespace(task_id=f"t{self.submitted}")

    def poll(self, task_id):
        return "succeeded", [{"file": "/v1/audio?path=x"}]

    def download(self, file_url):
        return generate_fixture_wav(str(self.submitted), 1, 1)


class FakeSeparator:
    name = "fake-separator"

    def separate(self, wav_body: bytes) -> dict[str, bytes]:
        return {"vocals": wav_body, "drums": wav_body, "bass": wav_body, "other": wav_body}


def _profile(client, token=TOKEN_A, name="Artist") -> dict:
    response = client.post("/api/v1/artist-profiles", json={"name": name}, headers=auth(token))
    assert response.status_code == 201
    return response.json()


def _upload_recording(client, profile_id: str, body: bytes, token=TOKEN_A,
                      filename="take.wav", key=None) -> dict:
    response = client.post(
        f"/api/v1/artist-profiles/{profile_id}/voice/dataset/recordings",
        files={"file": (filename, body, "audio/wav")},
        data={"consent": "own voice, own recordings"},
        headers=auth(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _library(client, profile_id: str, count: int = 2, token=TOKEN_A) -> dict:
    created = client.post(f"/api/v1/artist-profiles/{profile_id}/voice/dataset", headers=auth(token))
    assert created.status_code == 201
    for index in range(count):
        _upload_recording(client, profile_id, generate_fixture_wav(f"seed{index}", index, 2),
                          token=token, filename=f"take{index}.wav")
    return created.json()


def _finalize(client, profile_id: str, token=TOKEN_A) -> dict:
    response = client.post(f"/api/v1/artist-profiles/{profile_id}/voice/dataset/finalize",
                           headers=auth(token))
    assert response.status_code == 201, response.text
    return response.json()


def _training_worker(orch) -> TrainingWorker:
    workdir = Path(tempfile.mkdtemp(prefix="oal-train-"))
    settings = orch.settings.model_copy(update={
        "train_workdir": str(workdir),
        "adapter_cache_dir": str(workdir / "adapter-cache"),
    })
    return TrainingWorker(orch.db, orch.queue, orch.storage, settings,
                          adapter=FakeTrainAdapter(), gen_adapter=FakeGenAdapter(),
                          separator=FakeSeparator(), worker_id="test-train")


def _train_to_ready(client, orch, profile_id: str) -> tuple[TrainingWorker, str]:
    accepted = client.post(f"/api/v1/artist-profiles/{profile_id}/voice/train",
                           json={"model_selection": "ace-step-1.5-turbo", "max_epochs": 5},
                           headers=auth(TOKEN_A, **{"Idempotency-Key": "tr1"}))
    assert accepted.status_code == 202, accepted.text
    adapter_id = accepted.json()["adapter_id"]
    orch.dispatcher.publish_once()
    worker = _training_worker(orch)
    worker.run_once()
    return worker, adapter_id


# --- profiles -----------------------------------------------------------------


def test_profile_crud_and_ownership(client) -> None:
    profile = _profile(client)
    profile_id = profile["profile_id"]
    assert profile["default_voice_profile_id"] is None
    assert client.get(f"/api/v1/artist-profiles/{profile_id}", headers=auth(TOKEN_B)).status_code == 404
    stale = client.patch(f"/api/v1/artist-profiles/{profile_id}", json={"name": "X"},
                         headers=auth(TOKEN_A, **{"If-Match": '"9"'}))
    assert stale.status_code == 412
    ok = client.patch(f"/api/v1/artist-profiles/{profile_id}", json={"name": "X", "singer": {"timbre": "warm"}},
                      headers=auth(TOKEN_A, **{"If-Match": profile["etag"]}))
    assert ok.status_code == 200 and ok.json()["singer"] == {"timbre": "warm"}
    assert client.delete(f"/api/v1/artist-profiles/{profile_id}", headers=auth(TOKEN_A)).status_code == 204


# --- dataset + QC ---------------------------------------------------------------


def test_recording_upload_qc_and_duplicate(client) -> None:
    profile = _profile(client)
    profile_id = profile["profile_id"]
    recording = _upload_recording(client, profile_id, generate_fixture_wav("a", 1, 2))
    assert recording["qc"]["verdict"] == "usable"
    assert recording["duration_seconds"] and recording["duration_seconds"] > 0.5
    duplicate = client.post(
        f"/api/v1/artist-profiles/{profile_id}/voice/dataset/recordings",
        files={"file": ("again.wav", generate_fixture_wav("a", 1, 2), "audio/wav")},
        headers=auth(TOKEN_A))
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "RECORDING_DUPLICATE"
    bad_format = client.post(
        f"/api/v1/artist-profiles/{profile_id}/voice/dataset/recordings",
        files={"file": ("notes.txt", b"not audio", "text/plain")},
        headers=auth(TOKEN_A))
    assert bad_format.status_code == 422
    corrupt = client.post(
        f"/api/v1/artist-profiles/{profile_id}/voice/dataset/recordings",
        files={"file": ("bad.wav", b"not really a wav file at all", "audio/wav")},
        headers=auth(TOKEN_A))
    assert corrupt.status_code == 422 and corrupt.json()["error"]["code"] in ("QC_CORRUPT", "QC_PROBE_FAILED")


def test_recording_isolation_between_users(client) -> None:
    mine = _profile(client)
    _upload_recording(client, mine["profile_id"], generate_fixture_wav("a", 1, 2))
    other = _profile(client, token=TOKEN_B, name="Other")
    listing = client.get(f"/api/v1/artist-profiles/{other['profile_id']}/voice/dataset",
                         headers=auth(TOKEN_B))
    assert listing.status_code == 404  # other user has no library yet


def test_finalize_freezes_and_marks_stale(client, orch) -> None:
    profile = _profile(client)
    profile_id = profile["profile_id"]
    _library(client, profile_id, count=2)
    version = _finalize(client, profile_id)
    assert version["version_number"] == 1 and len(version["frozen_sha256"]) == 64
    assert version["report"]["recordings"] == 2
    worker, adapter_id = _train_to_ready(client, orch, profile_id)
    with orch.db.session() as session:
        adapter = session.get(VoiceAdapter, adapter_id)
        assert adapter.state == "ready"
        assert adapter.storage_prefix.startswith("owners/")
        assert "adapter_model.safetensors" in adapter.files_json
    # adding a recording and re-finalizing creates v2 and marks the adapter stale
    _upload_recording(client, profile_id, generate_fixture_wav("c", 3, 2))
    version2 = _finalize(client, profile_id)
    assert version2["version_number"] == 2
    assert version2["adapters_marked_stale"] == 1
    with orch.db.session() as session:
        adapter = session.get(VoiceAdapter, adapter_id)
        assert adapter.state == "stale"


def test_finalize_requires_usable_recordings(client) -> None:
    profile = _profile(client)
    client.post(f"/api/v1/artist-profiles/{profile['profile_id']}/voice/dataset", headers=auth(TOKEN_A))
    empty = client.post(f"/api/v1/artist-profiles/{profile['profile_id']}/voice/dataset/finalize",
                        headers=auth(TOKEN_A))
    assert empty.status_code == 422 and empty.json()["error"]["code"] == "DATASET_EMPTY"


# --- worker flows ---------------------------------------------------------------


def test_training_worker_registers_ready_adapter(client, orch) -> None:
    profile = _profile(client)
    _library(client, profile["profile_id"], count=2)
    _finalize(client, profile["profile_id"])
    worker, adapter_id = _train_to_ready(client, orch, profile["profile_id"])
    with orch.db.session() as session:
        job = session.execute(select(Job).where(Job.operation == "voice.train")).scalar_one()
        adapter = session.get(VoiceAdapter, adapter_id)
    assert job.status == "succeeded"
    assert adapter.state == "ready"
    assert adapter.metrics_json["steps"] == 42
    assert adapter.adapter_sha256 and len(adapter.adapter_sha256) == 64
    assert ("start", 5, 42) in worker.adapter.calls
    assert ("scan", True) in [(c[0], c[2]) for c in worker.adapter.calls if c[0] == "scan"]


def test_analyze_worker_builds_voice_profile(client, orch) -> None:
    profile = _profile(client)
    profile_id = profile["profile_id"]
    _library(client, profile_id, count=2)
    _finalize(client, profile_id)
    accepted = client.post(f"/api/v1/artist-profiles/{profile_id}/voice/analyze",
                           headers=auth(TOKEN_A, **{"Idempotency-Key": "an1"}))
    assert accepted.status_code == 202
    orch.dispatcher.publish_once()
    worker = _training_worker(orch)
    worker.run_once()
    with orch.db.session() as session:
        voice_profile = session.execute(select(VoiceProfile)).scalar_one()
    assert voice_profile.status == "analyzed"
    assert voice_profile.analysis_model == "mfcc-stats-v1"
    assert len(voice_profile.embeddings_json["recordings"]) == 2
    assert voice_profile.embeddings_json["centroid"]
    assert voice_profile.is_default is True


def test_validate_worker_validates_adapter(client, orch) -> None:
    profile = _profile(client)
    profile_id = profile["profile_id"]
    _library(client, profile_id, count=2)
    _finalize(client, profile_id)
    accepted = client.post(f"/api/v1/artist-profiles/{profile_id}/voice/analyze",
                           headers=auth(TOKEN_A, **{"Idempotency-Key": "an1"}))
    assert accepted.status_code == 202
    orch.dispatcher.publish_once()
    worker = _training_worker(orch)
    worker.run_once()
    _train_to_ready(client, orch, profile_id)
    with orch.db.session() as session:
        adapter = session.execute(select(VoiceAdapter)).scalar_one()
        adapter_id = adapter.id
    accepted = client.post(f"/api/v1/artist-profiles/{profile_id}/voice/validate",
                           json={"adapter_id": adapter_id},
                           headers=auth(TOKEN_A, **{"Idempotency-Key": "va1"}))
    assert accepted.status_code == 202
    orch.dispatcher.publish_once()
    worker.run_once()
    with orch.db.session() as session:
        adapter = session.get(VoiceAdapter, adapter_id)
    assert adapter.state == "validated"
    assert adapter.validation_json["passed"] is True
    assert adapter.validation_json["separator"] == "fake-separator"


# --- resolver / compatibility ------------------------------------------------------


def test_compatibility_states(client, orch) -> None:
    profile = _profile(client)
    profile_id = profile["profile_id"]
    response = client.get(f"/api/v1/artist-profiles/{profile_id}/voice/compatibility", headers=auth(TOKEN_A))
    assert response.status_code == 200
    states = {m["model_selection"]: m["state"] for m in response.json()["models"]}
    assert states["ace-step-1.5-turbo"] == "REFERENCE_CONDITIONING_AVAILABLE"
    _library(client, profile_id, count=1)
    _finalize(client, profile_id)
    states = {m["model_selection"]: m["state"]
              for m in client.get(f"/api/v1/artist-profiles/{profile_id}/voice/compatibility",
                                  headers=auth(TOKEN_A)).json()["models"]}
    assert states["ace-step-1.5-turbo"] == "ADAPTER_TRAINING_REQUIRED"
    _train_to_ready(client, orch, profile_id)
    states = {m["model_selection"]: m["state"]
              for m in client.get(f"/api/v1/artist-profiles/{profile_id}/voice/compatibility",
                                  headers=auth(TOKEN_A)).json()["models"]}
    assert states["ace-step-1.5-turbo"] == "ADAPTER_VALIDATION_REQUIRED"


def test_generation_voice_admission(client, orch) -> None:
    from conftest import submit

    profile = _profile(client)
    profile_id = profile["profile_id"]
    # no recordings at all -> best fidelity falls back to reference only if refs exist
    native_missing = submit(client, key="gen-native", artist_id=profile_id, voice_fidelity="native")
    assert native_missing.status_code == 409
    assert native_missing.json()["error"]["code"] == "VOICE_NOT_READY"

    _library(client, profile_id, count=1)
    reference = submit(client, key="gen-ref", artist_id=profile_id, voice_fidelity="reference")
    assert reference.status_code == 202, reference.text
    with orch.db.session() as session:
        job = session.execute(select(Job).where(Job.id == reference.json()["job_id"])).scalar_one()
        voice = job.request_json["_voice"]
        assert voice["voice_method"] == "reference"
        assert job.request_json["task_type"] == "cover"
        assert job.request_json["src_asset_id"] == voice["reference_asset_id"]

    _finalize(client, profile_id)
    _train_to_ready(client, orch, profile_id)
    with orch.db.session() as session:
        adapter = session.execute(select(VoiceAdapter)).scalar_one()
        adapter_id = adapter.id
    explicit = submit(client, key="gen-adapter", voice_adapter_id=adapter_id)
    assert explicit.status_code == 202
    conflict = submit(client, key="gen-conflict", artist_id=profile_id, voice_adapter_id=adapter_id)
    assert conflict.status_code == 422
    assert conflict.json()["error"]["code"] == "VOICE_BINDING_CONFLICT"
    unknown = submit(client, key="gen-unknown", voice_adapter_id="nope")
    assert unknown.status_code == 404


def test_generation_voice_incompatible_selection(client, orch) -> None:
    from conftest import submit

    profile = _profile(client)
    profile_id = profile["profile_id"]
    _library(client, profile_id, count=1)
    _finalize(client, profile_id)
    accepted = client.post(f"/api/v1/artist-profiles/{profile_id}/voice/train",
                           json={"model_selection": "ace-step-1.5-xl-sft"},
                           headers=auth(TOKEN_A, **{"Idempotency-Key": "tr-xl"}))
    adapter_id = accepted.json()["adapter_id"]
    with orch.db.session() as session:
        adapter = session.get(VoiceAdapter, adapter_id)
        adapter.state = "validated"
        session.commit()
    mismatch = client.post("/api/v1/jobs",
                           json={"operation": "music.generate", "model_id": "ace-step-1.5",
                                 "music_description": "x", "lyrics": "la la\n", "voice_adapter_id": adapter_id},
                           headers=auth(TOKEN_A, **{"Idempotency-Key": "gen-xl"}))
    assert mismatch.status_code == 422
    assert mismatch.json()["error"]["code"] == "VOICE_INCOMPATIBLE"


def test_voice_train_admission_guards(client) -> None:
    profile = _profile(client)
    profile_id = profile["profile_id"]
    no_data = client.post(f"/api/v1/artist-profiles/{profile_id}/voice/train",
                          json={"model_selection": "ace-step-1.5-turbo"},
                          headers=auth(TOKEN_A, **{"Idempotency-Key": "g1"}))
    assert no_data.status_code == 409
    _library(client, profile_id, count=1)
    _finalize(client, profile_id)
    bad_model = client.post(f"/api/v1/artist-profiles/{profile_id}/voice/train",
                            json={"model_selection": "heartmula"},
                            headers=auth(TOKEN_A, **{"Idempotency-Key": "g2"}))
    assert bad_model.status_code == 422
    assert bad_model.json()["error"]["code"] == "MODEL_VOICE_UNSUPPORTED"


def test_voice_profile_patch_and_default(client, orch) -> None:
    profile = _profile(client)
    profile_id = profile["profile_id"]
    _library(client, profile_id, count=1)
    _finalize(client, profile_id)
    accepted = client.post(f"/api/v1/artist-profiles/{profile_id}/voice/analyze",
                           headers=auth(TOKEN_A, **{"Idempotency-Key": "an1"}))
    orch.dispatcher.publish_once()
    _training_worker(orch).run_once()
    with orch.db.session() as session:
        voice_profile = session.execute(select(VoiceProfile)).scalar_one()
        vp_id = voice_profile.id
    patched = client.patch(f"/api/v1/artist-profiles/{profile_id}/voice/profiles/{vp_id}",
                           json={"description": {"timbre": "warm baritone"},
                                 "performance": {"intensity": "steady"}},
                           headers=auth(TOKEN_A))
    assert patched.status_code == 200
    assert patched.json()["description"] == {"timbre": "warm baritone"}
    assert patched.json()["performance"] == {"intensity": "steady"}
    default = client.post(f"/api/v1/artist-profiles/{profile_id}/voice/profiles/{vp_id}/set-default",
                          headers=auth(TOKEN_A))
    assert default.status_code == 200
    artist = client.get(f"/api/v1/artist-profiles/{profile_id}", headers=auth(TOKEN_A)).json()
    assert artist["default_voice_profile_id"] == vp_id
