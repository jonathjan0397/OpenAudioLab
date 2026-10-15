from __future__ import annotations

from sqlalchemy import select

from app.engine_acestep import EngineError, SubmitResult
from app.engine_worker import EngineWorker
from app.models import Asset, Job
from app.worker import generate_fixture_wav
from conftest import TOKEN_A, auth, submit


class FakeAdapter:
    model = "acestep-v15-turbo"

    def __init__(self, outcomes: list) -> None:
        self.outcomes = outcomes
        self.submitted: list[dict] = []
        self.polls = 0

    def build_payload(self, **kwargs) -> dict:
        return dict(kwargs)

    def submit(self, payload: dict) -> SubmitResult:
        self.submitted.append(payload)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, EngineError):
            raise outcome
        return SubmitResult(task_id="fake-task")

    def poll(self, task_id: str):
        self.polls += 1
        return self.outcomes.pop(0) if self.outcomes else ("pending", None)

    def download(self, file_url: str) -> bytes:
        return generate_fixture_wav("abc123", 7, 2)


def _worker(orch, adapter) -> EngineWorker:
    return EngineWorker(orch.db, orch.queue, orch.storage, adapter, orch.settings, worker_id="test-acestep")


def _status(db, job_id: str) -> str:
    with db.session() as session:
        return session.execute(select(Job).where(Job.id == job_id)).scalar_one().status


def test_engine_worker_happy_path(client, orch) -> None:
    adapter = FakeAdapter([SubmitResult(task_id="fake-task"), ("succeeded", {"file": "/v1/audio?path=x", "dit_model": "acestep-v15-turbo"})])
    worker = _worker(orch, adapter)
    response = submit(client, key="eng-1")
    job_id = response.json()["job_id"]
    orch.dispatcher.publish_once()
    assert worker.run_once() is True
    assert _status(orch.db, job_id) == "succeeded"

    with orch.db.session() as session:
        asset = session.execute(select(Asset).where(Asset.job_id == job_id)).scalar_one()
        assert asset.synthetic is False
        assert asset.role == "mix_wav"
    artifacts = client.get(f"/api/v1/jobs/{job_id}/artifacts", headers=auth(TOKEN_A)).json()["artifacts"]
    assert artifacts[0]["synthetic_test_audio"] is False


def test_engine_busy_requeues_without_failure(client, orch) -> None:
    adapter = FakeAdapter([EngineError("ENGINE_BUSY", "queue full")])
    worker = _worker(orch, adapter)
    job_id = submit(client, key="eng-2").json()["job_id"]
    orch.dispatcher.publish_once()
    worker.run_once()
    assert _status(orch.db, job_id) == "queued"


def test_engine_generation_failure(client, orch) -> None:
    adapter = FakeAdapter([SubmitResult(task_id="fake-task"), ("failed", None)])
    worker = _worker(orch, adapter)
    job_id = submit(client, key="eng-3").json()["job_id"]
    orch.dispatcher.publish_once()
    worker.run_once()
    assert _status(orch.db, job_id) == "failed"
    with orch.db.session() as session:
        job = session.execute(select(Job).where(Job.id == job_id)).scalar_one()
    assert job.error_code == "ENGINE_GENERATION_FAILED"


def test_cancel_during_poll_discards(client, orch) -> None:
    adapter = FakeAdapter([SubmitResult(task_id="fake-task")])
    worker = _worker(orch, adapter)
    job_id = submit(client, key="eng-4").json()["job_id"]
    orch.dispatcher.publish_once()

    import app.engine_worker as ew

    original_is_cancelling = ew.is_cancelling
    calls = {"n": 0}

    def fake_is_cancelling(db, jid):
        calls["n"] += 1
        if calls["n"] == 1:
            return False
        client.post(f"/api/v1/jobs/{jid}/cancel", headers=auth(TOKEN_A))
        return True

    ew.is_cancelling = fake_is_cancelling
    try:
        worker.run_once()
    finally:
        ew.is_cancelling = original_is_cancelling
    assert _status(orch.db, job_id) == "cancelled"
