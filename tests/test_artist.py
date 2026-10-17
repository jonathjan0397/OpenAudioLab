from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select

from app.models import ArtistProfileVersion, DatasetVersion, Evaluation, Job, TrainingRun
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


def _profile(client, token=TOKEN_A, name="Artist") -> dict:
    response = client.post("/api/v1/artist-profiles", json={"name": name}, headers=auth(token))
    assert response.status_code == 201
    return response.json()


def _upload_asset(client, body: bytes, token=TOKEN_A) -> str:
    session = client.post("/api/v1/assets/uploads", json={"filename": "t.wav"}, headers=auth(token)).json()
    client.put(f"/api/v1/assets/uploads/{session['upload_id']}/data", content=body, headers=auth(token))
    complete = client.post(f"/api/v1/assets/uploads/{session['upload_id']}/complete", headers=auth(token))
    assert complete.status_code == 201
    return complete.json()["asset"]["asset_id"]


def _dataset_with_tracks(client, profile_id: str, count: int = 3) -> dict:
    dataset = client.post(f"/api/v1/artist-profiles/{profile_id}/datasets", json={"name": "songs"},
                          headers=auth(TOKEN_A)).json()
    for index in range(count):
        asset_id = _upload_asset(client, generate_fixture_wav(f"seed{index}", index, 2))
        added = client.post(f"/api/v1/datasets/{dataset['dataset_id']}/tracks",
                            json={"asset_id": asset_id, "lyrics": f"line {index}",
                                  "labels": {"caption": "custom artist track"}},
                            headers=auth(TOKEN_A))
        assert added.status_code == 201
    return dataset


def _training_worker(orch) -> TrainingWorker:
    workdir = Path(tempfile.mkdtemp(prefix="oal-train-"))
    settings = orch.settings.model_copy(update={"train_workdir": str(workdir)})
    return TrainingWorker(orch.db, orch.queue, orch.storage, settings,
                          adapter=FakeTrainAdapter(), gen_adapter=FakeGenAdapter(), worker_id="test-train")


def _train_to_candidate(client, orch) -> tuple[TrainingWorker, str]:
    profile = _profile(client)
    dataset = _dataset_with_tracks(client, profile["profile_id"])
    version = client.post(f"/api/v1/datasets/{dataset['dataset_id']}/finalize", headers=auth(TOKEN_A)).json()
    accepted = client.post("/api/v1/trainings",
                           json={"profile_id": profile["profile_id"],
                                 "dataset_version_id": version["dataset_version_id"],
                                 "budget": {"max_epochs": 5}},
                           headers=auth(TOKEN_A, **{"Idempotency-Key": "tr1"}))
    assert accepted.status_code == 202
    orch.dispatcher.publish_once()
    worker = _training_worker(orch)
    worker.run_once()
    return worker, profile["profile_id"]


# --- profiles / rights ------------------------------------------------------


def test_profile_crud_and_ownership(client) -> None:
    profile = _profile(client)
    profile_id = profile["profile_id"]
    assert client.get(f"/api/v1/artist-profiles/{profile_id}", headers=auth(TOKEN_B)).status_code == 404
    stale = client.patch(f"/api/v1/artist-profiles/{profile_id}", json={"name": "X"},
                         headers=auth(TOKEN_A, **{"If-Match": '"9"'}))
    assert stale.status_code == 412
    ok = client.patch(f"/api/v1/artist-profiles/{profile_id}", json={"name": "X", "singer": {"timbre": "warm"}},
                      headers=auth(TOKEN_A, **{"If-Match": profile["etag"]}))
    assert ok.status_code == 200 and ok.json()["singer"] == {"timbre": "warm"}
    assert client.delete(f"/api/v1/artist-profiles/{profile_id}", headers=auth(TOKEN_A)).status_code == 204


def test_rights_records(client) -> None:
    profile = _profile(client)
    record = client.post(f"/api/v1/artist-profiles/{profile['profile_id']}/rights",
                         json={"purpose": "singer_identity", "declaration": "own voice, own recordings"},
                         headers=auth(TOKEN_A))
    assert record.status_code == 201
    bad = client.post(f"/api/v1/artist-profiles/{profile['profile_id']}/rights",
                      json={"purpose": "vibes", "declaration": "x"}, headers=auth(TOKEN_A))
    assert bad.status_code == 422
    listed = client.get(f"/api/v1/artist-profiles/{profile['profile_id']}/rights", headers=auth(TOKEN_A)).json()
    assert len(listed) == 1


# --- datasets ---------------------------------------------------------------


def test_dataset_finalize_splits_and_freezes(client) -> None:
    profile = _profile(client)
    dataset = _dataset_with_tracks(client, profile["profile_id"], count=3)
    version = client.post(f"/api/v1/datasets/{dataset['dataset_id']}/finalize", headers=auth(TOKEN_A)).json()
    assert version["split"]["train"] == 1 and version["split"]["validation"] == 1 and version["split"]["holdout"] == 1
    assert len(version["frozen_sha256"]) == 64
    again = client.post(f"/api/v1/datasets/{dataset['dataset_id']}/finalize", headers=auth(TOKEN_A))
    assert again.status_code == 409


def test_dataset_duplicate_track_rejected(client) -> None:
    profile = _profile(client)
    dataset = client.post(f"/api/v1/artist-profiles/{profile['profile_id']}/datasets", json={"name": "d"},
                          headers=auth(TOKEN_A)).json()
    asset_id = _upload_asset(client, generate_fixture_wav("dup", 1, 1))
    client.post(f"/api/v1/datasets/{dataset['dataset_id']}/tracks", json={"asset_id": asset_id}, headers=auth(TOKEN_A))
    duplicate = client.post(f"/api/v1/datasets/{dataset['dataset_id']}/tracks", json={"asset_id": asset_id},
                            headers=auth(TOKEN_A))
    assert duplicate.status_code == 409


# --- training admission -------------------------------------------------------


def test_training_admission_guards(client) -> None:
    profile = _profile(client)
    dataset = _dataset_with_tracks(client, profile["profile_id"])
    body = {"profile_id": profile["profile_id"], "dataset_version_id": "nope"}
    missing = client.post("/api/v1/trainings", json=body, headers=auth(TOKEN_A, **{"Idempotency-Key": "a1"}))
    assert missing.status_code == 404
    version = client.post(f"/api/v1/datasets/{dataset['dataset_id']}/finalize", headers=auth(TOKEN_A)).json()
    over = client.post("/api/v1/trainings",
                       json={"profile_id": profile["profile_id"], "dataset_version_id": version["dataset_version_id"],
                             "budget": {"max_epochs": 999999}},
                       headers=auth(TOKEN_A, **{"Idempotency-Key": "a2"}))
    assert over.status_code == 422 and over.json()["error"]["code"] == "BUDGET_EXCEEDED"


def test_training_requires_finalized_dataset(client) -> None:
    profile = _profile(client)
    dataset = _dataset_with_tracks(client, profile["profile_id"])
    accepted = client.post("/api/v1/trainings",
                           json={"profile_id": profile["profile_id"],
                                 "dataset_version_id": _open_version(client, dataset["dataset_id"])},
                           headers=auth(TOKEN_A, **{"Idempotency-Key": "a3"}))
    assert accepted.status_code == 409


def _open_version(client, dataset_id: str) -> str:
    # A dataset version id that exists but whose dataset is still open.
    version = client.post(f"/api/v1/datasets/{dataset_id}/finalize", headers=auth(TOKEN_A)).json()
    with client.app.state.db.session() as session:
        row = session.get(DatasetVersion, version["dataset_version_id"])
        from app.models import Dataset

        session.get(Dataset, row.dataset_id).status = "open"
        session.commit()
    return version["dataset_version_id"]


# --- workers --------------------------------------------------------------


def test_training_worker_registers_candidate(client, orch) -> None:
    worker, profile_id = _train_to_candidate(client, orch)
    with orch.db.session() as session:
        job = session.execute(select(Job).where(Job.operation == "artist.train")).scalar_one()
        run = session.execute(select(TrainingRun).where(TrainingRun.job_id == job.id)).scalar_one()
        version = session.execute(select(ArtistProfileVersion)).scalar_one()
    assert job.status == "succeeded"
    assert run.status == "succeeded" and run.metrics_json["steps"] == 42
    assert version.mechanism == "fine_tuned_adapter"
    assert version.state == "candidate" and version.evaluation_status == "none"
    assert version.artifacts_json["adapter_path"].endswith("adapter")
    assert ("start", 5, 42) in worker.adapter.calls


def test_evaluation_worker_measures_and_marks(client, orch) -> None:
    worker, profile_id = _train_to_candidate(client, orch)
    with orch.db.session() as session:
        version = session.execute(select(ArtistProfileVersion)).scalar_one()
        version_id = version.id
    accepted = client.post("/api/v1/evaluations",
                           json={"profile_version_id": version_id, "prompts": ["bright country rock"]},
                           headers=auth(TOKEN_A, **{"Idempotency-Key": "ev1"}))
    assert accepted.status_code == 202
    orch.dispatcher.publish_once()
    worker.run_once()
    with orch.db.session() as session:
        evaluation = session.execute(select(Evaluation)).scalar_one()
        version = session.get(ArtistProfileVersion, version_id)
    assert evaluation.measurements_json["prompt_0"]["candidate"]["sample_rate"] == 44100
    assert evaluation.measurements_json["prompt_0"]["base"]["bytes"] > 0
    assert version.evaluation_status == "measured"


# --- activation -------------------------------------------------------------


def test_activation_requires_measurement_and_supports_rollback(client, orch) -> None:
    worker, profile_id = _train_to_candidate(client, orch)
    with orch.db.session() as session:
        version = session.execute(select(ArtistProfileVersion)).scalar_one()
        version_id = version.id
    profile = client.get(f"/api/v1/artist-profiles/{profile_id}", headers=auth(TOKEN_A)).json()
    early = client.post(f"/api/v1/artist-profiles/{profile_id}/activate", json={"version_id": version_id},
                        headers=auth(TOKEN_A, **{"If-Match": profile["etag"]}))
    assert early.status_code == 409 and early.json()["error"]["code"] == "PROFILE_NOT_EVALUATED"

    client.post("/api/v1/evaluations", json={"profile_version_id": version_id, "prompts": ["p"]},
                headers=auth(TOKEN_A, **{"Idempotency-Key": "ev2"}))
    orch.dispatcher.publish_once()
    worker.run_once()

    profile = client.get(f"/api/v1/artist-profiles/{profile_id}", headers=auth(TOKEN_A)).json()
    activated = client.post(f"/api/v1/artist-profiles/{profile_id}/activate", json={"version_id": version_id},
                            headers=auth(TOKEN_A, **{"If-Match": profile["etag"]}))
    assert activated.status_code == 200
    assert activated.json()["active_version_id"] == version_id

    review = client.post(f"/api/v1/evaluations/{_evaluation_id(orch)}/review",
                         json={"review": "accept"}, headers=auth(TOKEN_A))
    assert review.status_code == 200


def _evaluation_id(orch) -> str:
    with orch.db.session() as session:
        return session.execute(select(Evaluation)).scalar_one().id


# --- generation admission -----------------------------------------------------


def test_generation_profile_admission(client, orch) -> None:
    worker, profile_id = _train_to_candidate(client, orch)
    with orch.db.session() as session:
        version = session.execute(select(ArtistProfileVersion)).scalar_one()
        version_id = version.id
    from conftest import submit

    ok = submit(client, key="gen-prof", artist_profile_version_id=version_id)
    assert ok.status_code == 202
    unknown = submit(client, key="gen-unknown", artist_profile_version_id="nope")
    assert unknown.status_code == 404
    with orch.db.session() as session:
        row = session.get(ArtistProfileVersion, version_id)
        row.base_model_id = "heartmula"
        session.commit()
    incompatible = submit(client, key="gen-bad", artist_profile_version_id=version_id)
    assert incompatible.status_code == 422
    assert incompatible.json()["error"]["code"] == "PROFILE_INCOMPATIBLE"
