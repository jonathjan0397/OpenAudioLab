"""M1 execution repairs: worker handler, reservations, gates, merge contract."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

_SEQ = iter(range(1, 10000))


@pytest.fixture(autouse=True)
def _admin_session(client):
    from app.models import User

    client.post("/api/v1/auth/logout")
    email = f"m1fix{next(_SEQ)}@example.com"
    resp = client.post("/api/v1/auth/register",
                       json={"email": email, "username": f"m1f{next(_SEQ)}",
                             "password": "super-secret-1"})
    uid = resp.json()["user"]["id"]
    with client.app.state.db.session() as session:
        session.get(User, uid).role = "admin"
        session.commit()


def _recording(client):
    from app.models import MlRecording, MlSource, new_uuid

    with client.app.state.db.session() as session:
        src = MlSource(id=new_uuid(), name=f"m1-src-{next(_SEQ)}", status="approved")
        session.add(src)
        session.commit()
        rec = MlRecording(id=new_uuid(), source_id=src.id, path=f"/x/{next(_SEQ)}.mp3",
                          sha256=f"m1-sha-{next(_SEQ)}", duration_seconds=180.0,
                          review_status="approved")
        session.add(rec)
        session.commit()
        return rec.id


def _reset_budget(client):
    from app.model_lab_train import get_budget

    with client.app.state.db.session() as session:
        b = get_budget(session)
        b.max_hours, b.max_spend_usd = 6.0, 3.0
        b.used_hours = b.spent_usd = b.reserved_usd = 0.0
        b.state = "open"
        session.commit()


def _dispatch(client, *, est_hours=1.0, est_spend=0.25):
    """Freeze a dataset, open a reserved attempt, attach + enqueue the job."""
    from app.model_lab_train import attach_job, get_budget, open_attempt
    from app.orchestration import claim_attempt, enqueue
    from app.models import MlDataset, new_uuid

    rec = _recording(client)
    with client.app.state.db.session() as session:
        ds = MlDataset(id=new_uuid(), name=f"m1-ds-{next(_SEQ)}",
                       manifest_json={"recording_ids": [rec]},
                       recording_count=1, frozen_sha256=f"ds-{next(_SEQ)}")
        session.add(ds)
        session.commit()
        budget = get_budget(session)
        attempt = open_attempt(session, ds, budget, est_hours=est_hours,
                               est_spend_usd=est_spend)
        job = attach_job(session, attempt, "m1-owner", client.app.state.settings)
        enqueue(session, job, client.app.state.settings)
        session.commit()
        return {"dataset": ds.id, "attempt": attempt.id, "job": job.id,
                "budget": budget.id}


def _claim(client, job_id):
    from app.orchestration import claim_attempt

    return claim_attempt(client.app.state.db, job_id, "m1-worker")


def _worker(client):
    from app.training_worker import TrainingWorker

    w = SimpleNamespace(db=client.app.state.db, queue=None,
                        storage=client.app.state.storage,
                        settings=client.app.state.settings,
                        worker_id="m1-worker", node_key="m1-test-node")
    w._supervised_run = lambda *a, **k: TrainingWorker._supervised_run(w, *a, **k)
    w._kill_group = TrainingWorker._kill_group
    w._last_json = TrainingWorker._last_json
    w._release_node = lambda: TrainingWorker._release_node(w)
    return w


class _FakeProc:
    def __init__(self, command, stdout=None, **kw):
        self.pid = 4242
        self.returncode = 0
        if stdout is not None:
            stdout.write(_FakeProc.stdout_line + "\n")
            stdout.flush()

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0


_FakeProc.stdout_line = ""


def _job(client, job_id):
    from app.orchestration import get_job_by_id

    with client.app.state.db.session() as session:
        return get_job_by_id(session, job_id)


def test_trainer_unavailable_fails_attempt(client) -> None:
    _reset_budget(client)
    from app.training_worker import TrainingWorker

    ids = _dispatch(client)
    claimed = _claim(client, ids["job"])
    assert claimed is not None
    _, attempt_id, lease = claimed
    client.app.state.settings.model_lab_train_command = ""
    TrainingWorker._model_lab_train(_worker(client), ids["job"], attempt_id, lease)
    job = _job(client, ids["job"])
    assert job.status == "failed" and job.error_code == "TRAINER_UNAVAILABLE"


def test_trainer_success_settles_budget_once(client, monkeypatch) -> None:
    _reset_budget(client)
    import app.training_worker as tw
    from app.models import MlBudget, MlTrainingAttempt

    ids = _dispatch(client)
    claimed = _claim(client, ids["job"])
    _, attempt_id, lease = claimed
    client.app.state.settings.model_lab_train_command = "echo train"
    _FakeProc.stdout_line = ('{"artifact_key": "ml/a.pt", "sha256": "aa", '
                             '"hours": 1.0, "spend_usd": 0.1}')
    monkeypatch.setattr(tw.subprocess, "Popen", _FakeProc)
    monkeypatch.setattr(tw.time, "sleep", lambda s: None)
    tw.TrainingWorker._model_lab_train(_worker(client), ids["job"], attempt_id, lease)
    assert _job(client, ids["job"]).status == "succeeded"
    with client.app.state.db.session() as session:
        attempt = session.get(MlTrainingAttempt, ids["attempt"])
        assert attempt.state == "done" and attempt.settled is True
        budget = session.get(MlBudget, ids["budget"])
        assert budget.used_hours == 1.0 and budget.spent_usd == 0.1
        assert budget.reserved_usd == 0.0  # reservation released
        # replay settlement must not double-book
        from app.model_lab_train import settle_attempt

        settle_attempt(session, attempt, state="done", hours=1.0, spend_usd=0.1,
                       budget=budget)
        assert budget.used_hours == 1.0 and budget.spent_usd == 0.1


def test_trainer_noop_fails(client, monkeypatch) -> None:
    _reset_budget(client)
    import app.training_worker as tw
    from app.models import MlBudget, MlTrainingAttempt

    ids = _dispatch(client)
    _, attempt_id, lease = _claim(client, ids["job"])
    client.app.state.settings.model_lab_train_command = "echo train"
    _FakeProc.stdout_line = "nothing to see here"
    monkeypatch.setattr(tw.subprocess, "Popen", _FakeProc)
    monkeypatch.setattr(tw.time, "sleep", lambda s: None)
    tw.TrainingWorker._model_lab_train(_worker(client), ids["job"], attempt_id, lease)
    with client.app.state.db.session() as session:
        attempt = session.get(MlTrainingAttempt, ids["attempt"])
        assert attempt.state == "failed" and "TRAINING_NO_ARTIFACT" in attempt.error
        budget = session.get(MlBudget, ids["budget"])
        assert budget.spent_usd == 0.0 and budget.reserved_usd == 0.0


def test_reservation_blocks_without_headroom(client) -> None:
    from app.model_lab_train import BudgetError, get_budget, open_attempt
    from app.models import MlDataset, new_uuid

    rec = _recording(client)
    with client.app.state.db.session() as session:
        budget = get_budget(session)
        budget.max_spend_usd = 0.3
        budget.used_hours = 0.0
        budget.spent_usd = 0.0
        budget.reserved_usd = 0.0
        budget.state = "open"
        session.commit()
        ds = MlDataset(id=new_uuid(), name=f"m1-ds-{next(_SEQ)}",
                       manifest_json={"recording_ids": [rec]}, recording_count=1,
                       frozen_sha256=f"ds-{next(_SEQ)}")
        session.add(ds)
        session.commit()
        first = open_attempt(session, ds, budget, est_hours=0.5, est_spend_usd=0.25)
        assert first.reserved_usd == 0.25 and budget.reserved_usd == 0.25
        with pytest.raises(BudgetError):
            open_attempt(session, ds, budget, est_hours=0.5, est_spend_usd=0.25)


def test_attach_job_keeps_attempt_queued_until_claim(client) -> None:
    _reset_budget(client)
    from app.models import MlTrainingAttempt

    ids = _dispatch(client)
    with client.app.state.db.session() as session:
        assert session.get(MlTrainingAttempt, ids["attempt"]).state == "queued"
    _claim(client, ids["job"])
    with client.app.state.db.session() as session:
        assert session.get(MlTrainingAttempt, ids["attempt"]).state == "queued"


def test_merge_recipe_accepts_zero_and_one_adapter(client) -> None:
    from app.models import Lora, new_uuid

    with client.app.state.db.session() as session:
        a = Lora(id=f"m1-a{next(_SEQ)}", name=f"m1-a-{next(_SEQ)}", kind="genre", state="active")
        session.add(a)
        session.commit()
        aid = a.id
    original = client.app.state.settings.model_lab_merge_command
    client.app.state.settings.model_lab_merge_command = "echo merge"
    zero = client.post("/api/v1/admin/model-lab/merge-recipes",
                       json={"name": "ctrl-0", "base_model": "m", "adapter_ids": []})
    assert zero.status_code == 201
    one = client.post("/api/v1/admin/model-lab/merge-recipes",
                      json={"name": "ctrl-1", "base_model": "m", "adapter_ids": [aid]})
    assert one.status_code == 201
    run = client.post(f"/api/v1/admin/model-lab/merge-recipes/{zero.json()['id']}/run")
    assert run.status_code == 202 and run.json()["state"] == "building"
    client.app.state.settings.model_lab_merge_command = original


def test_swappiness_zero_respects_hard_gates() -> None:
    from scripts.autoscale import swappiness_gate

    fset = {"swappiness": 0, "auto_burst_enabled": True,
            "max_auto_burst_workers": 2, "daily_burst_budget_usd": 1.0}
    allow, decision, reason, _ = swappiness_gate(3600, 3, fset, 0, 1.0)
    assert (allow, decision, reason) == (False, "DECLINE", "BUDGET_EXHAUSTED")
    allow, decision, reason, _ = swappiness_gate(3600, 3, fset, 2, 0.0)
    assert (allow, decision, reason) == (False, "DECLINE", "EXISTING_REMOTE_CAPACITY")
    allow, decision, reason, _ = swappiness_gate(0, 3, fset, 0, 0.0)
    assert (allow, decision, reason) == (True, "PROVISION", "DEPTH_POLICY")


def test_promotion_gate_fail_and_integrity(client) -> None:
    from app.models import MlModelBundle, new_uuid

    with client.app.state.db.session() as session:
        b = MlModelBundle(id=new_uuid(), name=f"m1-b-{next(_SEQ)}", version="v1",
                          kind="merged", base_model="m", state="released",
                          sha256="ab" * 32)
        session.add(b)
        session.commit()
        bid = b.id
    client.post(f"/api/v1/admin/model-lab/bundles/{bid}/evaluations",
                json={"kind": "ab", "verdict": "win"})
    gate = client.get(f"/api/v1/admin/model-lab/bundles/{bid}/promotion-gate").json()
    assert gate["ready"] is True
    client.post(f"/api/v1/admin/model-lab/bundles/{bid}/evaluations",
                json={"kind": "objective", "verdict": "fail"})
    gate = client.get(f"/api/v1/admin/model-lab/bundles/{bid}/promotion-gate").json()
    assert gate["ready"] is False and any("failing" in r for r in gate["reasons"])
    blocked = client.post("/api/v1/admin/model-lab/release-channels/stable/promote",
                          json={"bundle_id": bid})
    assert blocked.status_code == 409
    with client.app.state.db.session() as session:
        b2 = MlModelBundle(id=new_uuid(), name=f"m1-b2-{next(_SEQ)}", version="v1",
                           kind="merged", base_model="m", state="released")
        session.add(b2)
        session.commit()
        b2id = b2.id
    client.post(f"/api/v1/admin/model-lab/bundles/{b2id}/evaluations",
                json={"kind": "objective", "verdict": "pass"})
    gate = client.get(f"/api/v1/admin/model-lab/bundles/{b2id}/promotion-gate").json()
    assert gate["ready"] is False and any("integrity" in r for r in gate["reasons"])
