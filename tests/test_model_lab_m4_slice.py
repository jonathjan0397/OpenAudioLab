"""M4 vertical slice: import -> review -> freeze -> reserve -> train -> export -> register."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

_SEQ = iter(range(1, 10000))

ACC = ('"steps": 48, "acceptance": {"lora_load": true, "loadable": true, '
        '"tensors": 8, "inference_bytes": 4200, '
        '"sample_path": "/nonexistent/acc.mp3"}')



@pytest.fixture(autouse=True)
def _admin_session(client):
    from app.models import User

    client.post("/api/v1/auth/logout")
    email = f"m4slice{next(_SEQ)}@example.com"
    resp = client.post("/api/v1/auth/register",
                       json={"email": email, "username": f"m4s{next(_SEQ)}",
                             "password": "super-secret-1"})
    uid = resp.json()["user"]["id"]
    with client.app.state.db.session() as session:
        session.get(User, uid).role = "admin"
        session.commit()


def _reset_budget(client):
    from app.model_lab_train import get_budget

    with client.app.state.db.session() as session:
        b = get_budget(session)
        b.max_hours, b.max_spend_usd = 6.0, 3.0
        b.used_hours = b.spent_usd = b.reserved_usd = 0.0
        b.state = "open"
        session.commit()


class _FakeProc:
    stdout_line = ""

    def __init__(self, command, stdout=None, **kw):
        self.pid = 99
        self.returncode = 0
        if stdout is not None:
            stdout.write(_FakeProc.stdout_line + "\n")
            stdout.flush()

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0


def test_deterministic_caption_prefers_fields_then_stem() -> None:
    from types import SimpleNamespace

    from app.model_lab import deterministic_caption

    rec = SimpleNamespace(artist="Alabama", title="Song Of The South", genre_raw="Country")
    assert deterministic_caption(rec, "/x/any.mp3") == "Alabama - Song Of The South, Country"
    bare = SimpleNamespace(artist=None, title=None, genre_raw=None)
    assert deterministic_caption(bare, "/x/Strip It Down.mp3") == "Strip It Down"
    artist_only = SimpleNamespace(artist="Alabama", title=None, genre_raw=None)
    assert deterministic_caption(artist_only, "/x/x.mp3") == "Alabama"


def test_freeze_embeds_caption_in_manifest(client) -> None:
    from app.models import MlRecording, MlSource, new_uuid

    with client.app.state.db.session() as session:
        src = MlSource(id=new_uuid(), name=f"cap-src-{next(_SEQ)}", status="approved")
        session.add(src)
        session.commit()
        rec = MlRecording(id=new_uuid(), source_id=src.id,
                          path="/x/Strip It Down.mp3", sha256=f"cap-{next(_SEQ)}",
                          duration_seconds=200.0, review_status="approved",
                          dataset_eligible=True)
        session.add(rec)
        from app.models import MlRightsRecord
        session.add(MlRightsRecord(id=new_uuid(), recording_id=rec.id, holder="owner",
                                   scope="recording", evidence="cap declaration"))
        session.commit()
        rid = rec.id
    ds = client.post("/api/v1/admin/model-lab/datasets",
                     json={"name": f"cap-ds-{next(_SEQ)}", "recording_ids": [rid]})
    assert ds.status_code == 201
    from app.models import MlDataset

    with client.app.state.db.session() as session:
        entry = session.get(MlDataset, ds.json()["id"]).manifest_json["entries"][0]
    assert entry["caption"] == "Strip It Down"


def test_vertical_slice_end_to_end(client, monkeypatch, tmp_path) -> None:
    import app.training_worker as tw
    from app.models import (FleetNode, Job, MlBudget, MlDataset, MlModelBundle,
                            MlRecording, MlSource, MlTrainingAttempt, new_uuid)
    from app.orchestration import claim_attempt
    from app.training_worker import TrainingWorker

    _reset_budget(client)

    # 1-2. import + review
    with client.app.state.db.session() as session:
        src = MlSource(id=new_uuid(), name=f"slice-src-{next(_SEQ)}", status="approved")
        session.add(src)
        session.commit()
        rec = MlRecording(id=new_uuid(), source_id=src.id, path=f"/s/{next(_SEQ)}.mp3",
                          sha256=f"slice-{next(_SEQ)}", duration_seconds=200.0,
                          review_status="unreviewed")
        session.add(rec)
        session.commit()
        from app.models import MlRightsRecord
        session.add(MlRightsRecord(id=new_uuid(), recording_id=rec.id, holder="owner",
                                   scope="recording", evidence="slice declaration"))
        session.commit()
        rid = rec.id
    review = client.post(f"/api/v1/admin/model-lab/recordings/{rid}/review",
                         json={"decision": "approved", "reviewer": "curator"})
    assert review.status_code == 200

    # 3. freeze
    ds = client.post("/api/v1/admin/model-lab/datasets",
                     json={"name": f"slice-ds-{next(_SEQ)}", "recording_ids": [rid]})
    assert ds.status_code == 201
    dataset_id = ds.json()["id"]

    # 4. reserve + dispatch (budget-gated)
    train = client.post(f"/api/v1/admin/model-lab/datasets/{dataset_id}/train")
    assert train.status_code == 202
    attempt_id, job_id = train.json()["attempt"], train.json()["job_id"]
    with client.app.state.db.session() as session:
        assert session.get(MlBudget, session.get(MlTrainingAttempt, attempt_id).budget_id
                           ).reserved_usd > 0.0

    # node under the fleet contract, shared_ready -> worker self-claims
    from app.fleet_nodes import register_node

    with client.app.state.db.session() as session:
        register_node(session, "slice-node", worker_id="w-slice")

    # 5. train on the worker
    claimed = claim_attempt(client.app.state.db, job_id, "w-slice")
    assert claimed is not None
    _, att, lease = claimed
    export = tmp_path / "adapter.safetensors"
    export.write_bytes(b"weights")
    client.app.state.settings.model_lab_train_command = "echo train"
    sample_file = tmp_path / "acc-sample.mp3"
    sample_file.write_bytes(b"tiny-sample-audio")
    client.app.state.settings.review_dir = str(tmp_path / "review")
    _FakeProc.stdout_line = ('{"artifact_key": "pending", "sha256": "ca' + "fe" * 31 +
                             f'", "hours": 1.5, "spend_usd": 0.2, '
                             '"steps": 12, "acceptance": {"lora_load": true, "loadable": true, '
                             f'"tensors": 8, "inference_bytes": 4200, "sample_path": "{sample_file}"}}, '
                             f'"export_path": "{export}", "name": "slice-adapter"}}')
    monkeypatch.setattr(tw.subprocess, "Popen", _FakeProc)
    monkeypatch.setattr(tw.time, "sleep", lambda s: None)
    w = SimpleNamespace(db=client.app.state.db, storage=client.app.state.storage,
                        settings=client.app.state.settings, worker_id="w-slice",
                        node_key="slice-node")
    w._supervised_run = lambda *a, **k: TrainingWorker._supervised_run(w, *a, **k)
    w._kill_group = TrainingWorker._kill_group
    w._last_json = TrainingWorker._last_json
    w._release_node = lambda: TrainingWorker._release_node(w)
    w._load_fresh = lambda path: None
    TrainingWorker._model_lab_train(w, job_id, att, lease)

    # 6-8. export -> reload(skipped) -> register
    with client.app.state.db.session() as session:
        job = session.execute(
            __import__("sqlalchemy").select(Job).where(Job.id == job_id)).scalar_one()
        assert job.status == "succeeded"
        attempt = session.get(MlTrainingAttempt, attempt_id)
        assert attempt.state == "done" and attempt.settled
        bundle = session.execute(
            __import__("sqlalchemy").select(MlModelBundle)
            .where(MlModelBundle.name == "slice-adapter")).scalar_one()
        assert bundle.kind == "adapter" and bundle.state == "candidate"
        assert bundle.sha256 and bundle.artifact_key == f"ml/adapters/{att}/model.safetensors"
        assert bundle.bundle_json["reload"] == "skipped"
        assert bundle.bundle_json["frozen_sha256"] == \
            session.get(MlDataset, dataset_id).frozen_sha256
        node = session.get(FleetNode, "slice-node")
        assert node.state == "shared_ready"  # released after cleanup
        budget = session.get(MlBudget, attempt.budget_id)
        assert budget.used_hours == 1.5 and budget.spent_usd == 0.2
        assert budget.reserved_usd == 0.0
    assert client.app.state.storage.exists(bundle.artifact_key)
    assert client.app.state.storage.get(bundle.artifact_key).body == b"weights"
    assert (tmp_path / "review" / bundle.id / "acceptance-sample.mp3").is_file()  # local review mirror
