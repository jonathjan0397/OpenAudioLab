"""GPU orchestration M1: Smart Model Queue Manager (SMQM) selection tests."""

from __future__ import annotations

from sqlalchemy import select

from app.engine_acestep import SubmitResult
from app.engine_worker import EngineWorker
from app.models import Job, utcnow
from conftest import auth, submit
from test_engine_worker import FakeAdapter

TURBO = "acestep-v15-turbo"


class FakeEngineProcess:
    """Mimics AceStepProcess swap semantics: a model change stops the server."""

    def __init__(self, model: str) -> None:
        self.model = model
        self.stops = 0

    def is_running(self) -> bool:
        return True

    def ensure_running(self, model: str | None = None) -> None:
        if model and model != self.model:
            self.stops += 1
            self.model = model

    def stop(self) -> None:
        self.stops += 1


def _worker(orch, adapter, engine=None) -> EngineWorker:
    return EngineWorker(
        orch.db, orch.queue, orch.storage, adapter, orch.settings,
        worker_id="test-smqm", engine_process=engine,
    )


def _submit(client, orch, title: str, family: str = "turbo") -> str:
    r = submit(client, key=f"smqm-{title}", title=title)
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    if family != "turbo":
        with orch.db.session() as session:
            job = session.execute(select(Job).where(Job.id == job_id)).scalar_one()
            job.request_json = {
                **(job.request_json or {}),
                "_admission": {"family": family, "engine_model": f"acestep-v15-{family}-x",
                               "execution_profile_id": f"{family}-v1"},
            }
            session.commit()
    return job_id


def _status(client, orch, title: str) -> str:
    with orch.db.session() as session:
        for j in session.execute(select(Job)).scalars():
            if (j.request_json or {}).get("title") == title:
                return j.status
    raise AssertionError(f"no job titled {title}")


def _outcomes(n: int) -> list:
    out: list = []
    for i in range(n):
        out.append(SubmitResult(task_id=f"smqm-{i}"))
        out.append(("succeeded", [{"file": "/v1/audio?path=x", "dit_model": "m"}]))
    return out


def _always_runnable(worker: EngineWorker) -> EngineWorker:
    worker._can_run_profile = lambda adm: (True, "")  # type: ignore[method-assign]
    return worker


def test_same_model_jobs_run_consecutively(client, orch) -> None:
    """§19.1: with Turbo loaded, Turbo jobs are preferred over the older XL job."""
    _submit(client, orch, "q1-xl", "xl")
    _submit(client, orch, "q1-t1", "turbo")
    _submit(client, orch, "q1-t2", "turbo")
    orch.dispatcher.publish_once()
    worker = _always_runnable(_worker(orch, FakeAdapter(_outcomes(3)), FakeEngineProcess(TURBO)))
    assert worker.run_once() is True
    assert _status(client, orch, "q1-t1") == "succeeded"
    assert _status(client, orch, "q1-xl") == "queued"
    assert worker.run_once() is True
    assert _status(client, orch, "q1-t2") == "succeeded"
    assert worker.run_once() is True  # turbo exhausted -> immediate switch to XL
    assert _status(client, orch, "q1-xl") == "succeeded"


def test_no_unnecessary_checkpoint_reload(client, orch) -> None:
    """§19.2: consecutive same-model jobs must not restart the engine."""
    _submit(client, orch, "q2-t1", "turbo")
    _submit(client, orch, "q2-t2", "turbo")
    orch.dispatcher.publish_once()
    engine = FakeEngineProcess(TURBO)
    worker = _always_runnable(_worker(orch, FakeAdapter(_outcomes(2)), engine))
    assert worker.run_once() is True
    assert worker.run_once() is True
    assert engine.stops == 0


def test_immediate_switch_when_loaded_exhausted(client, orch) -> None:
    """§19.3: no waiting for the idle timer when only another model has work."""
    _submit(client, orch, "q3-xl", "xl")
    orch.dispatcher.publish_once()
    engine = FakeEngineProcess(TURBO)
    worker = _always_runnable(_worker(orch, FakeAdapter(_outcomes(1)), engine))
    assert worker.run_once() is True
    assert _status(client, orch, "q3-xl") == "succeeded"
    assert engine.stops == 1  # exactly one swap, at claim time


def test_fairness_batch_cap_forces_switch(client, orch, monkeypatch) -> None:
    """§19.4: continuous Turbo demand cannot starve XL beyond the batch window."""
    monkeypatch.setattr(orch.settings, "model_batch_max_jobs", 2)
    _submit(client, orch, "q4-xl", "xl")
    _submit(client, orch, "q4-t1", "turbo")
    _submit(client, orch, "q4-t2", "turbo")
    _submit(client, orch, "q4-t3", "turbo")
    orch.dispatcher.publish_once()
    worker = _always_runnable(_worker(orch, FakeAdapter(_outcomes(3)), FakeEngineProcess(TURBO)))
    assert worker.run_once() is True
    assert _status(client, orch, "q4-t1") == "succeeded"
    assert worker.run_once() is True
    assert _status(client, orch, "q4-t2") == "succeeded"
    assert worker.run_once() is True  # batch cap reached -> XL goes first
    assert _status(client, orch, "q4-xl") == "succeeded"
    assert _status(client, orch, "q4-t3") == "queued"


def test_incompatible_job_skipped_not_looped(client, orch) -> None:
    """§19.5: an XL job the worker cannot run stays queued; the Turbo job runs."""
    _submit(client, orch, "q5-xl", "xl")
    _submit(client, orch, "q5-t1", "turbo")
    orch.dispatcher.publish_once()
    worker = _worker(orch, FakeAdapter(_outcomes(1)), FakeEngineProcess(TURBO))
    assert worker.run_once() is True
    assert _status(client, orch, "q5-t1") == "succeeded"
    assert _status(client, orch, "q5-xl") == "queued"
    assert orch.queue.depth("oal:queue:ace-step-1.5") == 1  # XL hint preserved


def test_retry_backoff_skipped(client, orch) -> None:
    """§19.6: a job inside its retry window is not selected."""
    t1 = _submit(client, orch, "q6-t1", "turbo")
    _submit(client, orch, "q6-t2", "turbo")
    orch.dispatcher.publish_once()
    with orch.db.session() as session:
        job = session.execute(select(Job).where(Job.id == t1)).scalar_one()
        job.next_retry_at = utcnow().replace(year=utcnow().year + 1)
        session.commit()
    worker = _always_runnable(_worker(orch, FakeAdapter(_outcomes(1)), FakeEngineProcess(TURBO)))
    assert worker.run_once() is True
    assert _status(client, orch, "q6-t2") == "succeeded"
    assert _status(client, orch, "q6-t1") == "queued"


def test_lost_race_removes_stale_hint(client, orch, monkeypatch) -> None:
    """§19.8: a failed claim (another worker won) must LREM the consumed hint."""
    import app.engine_worker as ew

    _submit(client, orch, "q8-t1", "turbo")
    orch.dispatcher.publish_once()
    monkeypatch.setattr(ew, "claim_attempt", lambda *a, **k: None)
    worker = _always_runnable(_worker(orch, FakeAdapter([]), FakeEngineProcess(TURBO)))
    assert worker.run_once() is True
    assert orch.queue.depth("oal:queue:ace-step-1.5") == 0


def test_gpu_fleet_queues_endpoint(client) -> None:
    from app.models import User

    client.post("/api/v1/auth/logout")
    r = client.post(
        "/api/v1/auth/register",
        json={"email": "fleet@example.com", "username": "fleet", "password": "super-secret-1"},
    )
    uid = r.json()["user"]["id"]
    with client.app.state.db.session() as session:
        session.get(User, uid).role = "admin"
        session.commit()
    body = client.get("/api/v1/admin/gpu-fleet/queues")
    assert body.status_code == 200
    data = body.json()
    assert "models" in data and "workers" in data and "queue_depths" in data
