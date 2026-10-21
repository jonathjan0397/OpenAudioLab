from __future__ import annotations

import time

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
        return outcome

    def poll(self, task_id: str):
        self.polls += 1
        if not self.outcomes:
            return ("pending", None)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, EngineError):
            raise outcome
        return outcome

    def download(self, file_url: str) -> bytes:
        return generate_fixture_wav("abc123", 7, 2)


def _worker(orch, adapter) -> EngineWorker:
    return EngineWorker(orch.db, orch.queue, orch.storage, adapter, orch.settings, worker_id="test-acestep")


def _status(db, job_id: str) -> str:
    with db.session() as session:
        return session.execute(select(Job).where(Job.id == job_id)).scalar_one().status


def test_engine_worker_happy_path(client, orch) -> None:
    adapter = FakeAdapter([SubmitResult(task_id="fake-task"), ("succeeded", [{"file": "/v1/audio?path=x", "dit_model": "acestep-v15-turbo"}])])
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
    manifest = artifacts[0]["manifest"]
    assert manifest["effective"]["engine_version"].startswith("ace-step-1.5/")
    assert manifest["effective"]["upstream"]["task_id"] == "fake-task"


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


class FakeProcess:
    def __init__(self, running: bool = False, ensure_raises: EngineError | None = None) -> None:
        self._running = running
        self.ensure_raises = ensure_raises
        self.ensure_calls = 0
        self.stopped = False
        self.model = None

    def is_running(self) -> bool:
        return self._running

    def ensure_running(self, model: str | None = None) -> None:
        self.ensure_calls += 1
        if model and self.model and model != self.model:
            self.stopped = True  # swap stops the previous engine first
        if self.ensure_raises is not None:
            raise self.ensure_raises
        self.model = model or self.model
        self._running = True

    def stop(self) -> None:
        self.stopped = True
        self._running = False


def test_idle_stop_stops_engine(client, orch) -> None:
    proc = FakeProcess(running=True)
    worker = EngineWorker(
        orch.db, orch.queue, orch.storage, FakeAdapter([]), orch.settings,
        worker_id="t-idle", engine_process=proc,
    )
    original = orch.settings.engine_idle_stop_seconds
    orch.settings.engine_idle_stop_seconds = 0.001
    try:
        worker._last_activity = time.monotonic() - 10
        assert worker.run_once() is False  # empty queue -> idle tick
        assert proc.stopped is True
    finally:
        orch.settings.engine_idle_stop_seconds = original


def test_engine_start_failure_requeues(client, orch) -> None:
    import app.engine_worker as ew

    proc = FakeProcess(running=False, ensure_raises=EngineError("ENGINE_START_FAILED", "boom"))
    worker = EngineWorker(
        orch.db, orch.queue, orch.storage, FakeAdapter([]), orch.settings,
        worker_id="t-start", engine_process=proc,
    )
    job_id = submit(client, key="eng-5").json()["job_id"]
    orch.dispatcher.publish_once()
    original_sleep = ew.time.sleep
    ew.time.sleep = lambda *_: None
    try:
        assert worker.run_once() is True
    finally:
        ew.time.sleep = original_sleep
    assert _status(orch.db, job_id) == "queued"
    assert proc.ensure_calls == 1


def test_worker_receive_queues_by_tier(orch) -> None:
    base = EngineWorker(orch.db, orch.queue, orch.storage, FakeAdapter([]), orch.settings, worker_id="t-base")
    assert base.receive_queues == ["oal:queue:ace-step-1.5", "oal:queue:ace-step-1.5:burst"]
    burst_settings = orch.settings.model_copy(update={"worker_tier": "burst"})
    burst = EngineWorker(orch.db, orch.queue, orch.storage, FakeAdapter([]), burst_settings, worker_id="t-burst")
    assert burst.receive_queues == ["oal:queue:ace-step-1.5:burst"]


def test_payload_forwards_resolved_controls_not_raw(orch) -> None:
    # Regression: the worker must send the API's profile-resolved controls (steps/cfg/
    # shift defaults) so non-turbo models run at their denoising settings, not the
    # engine's REST default of 8 steps. Raw controls were empty here and must be ignored.
    from types import SimpleNamespace
    worker = _worker(orch, FakeAdapter([]))
    job = SimpleNamespace(
        request_json={
            "music_description": "x", "instrumental": True, "seed": 5, "duration_seconds": 12,
            "controls": {},
            "_admission": {"resolved_controls": {"inference_steps": 64, "guidance_scale": 7.0, "shift": 1.0}},
        },
        lyrics=None, owner_id="usr_x",
    )
    payload = worker._payload_for(job)
    assert payload["controls"] == {"inference_steps": 64, "guidance_scale": 7.0, "shift": 1.0}


def test_payload_falls_back_to_raw_controls_without_admission(orch) -> None:
    # Legacy/no-admission jobs keep the prior behavior (forward whatever was sent).
    from types import SimpleNamespace
    worker = _worker(orch, FakeAdapter([]))
    job = SimpleNamespace(
        request_json={"music_description": "x", "controls": {"inference_steps": 50}},
        lyrics=None, owner_id="usr_x",
    )
    payload = worker._payload_for(job)
    assert payload["controls"] == {"inference_steps": 50}


def test_attempt_heartbeat_thread_beats_during_setup(monkeypatch, orch) -> None:
    # Regression: the XL swap/load happens after claim but BEFORE the poll loop, so a
    # dedicated heartbeat thread must keep the lease alive across setup (else the
    # reconciler falsely marks a live loading attempt "interrupted" -> MAX_ATTEMPTS).
    from app import engine_worker as ew
    beats: list[str] = []
    monkeypatch.setattr(ew, "heartbeat", lambda db, aid, tok: (beats.append(aid), True)[1])
    settings = orch.settings.model_copy(update={"lease_seconds": 1})
    worker = EngineWorker(orch.db, orch.queue, orch.storage, FakeAdapter([]), settings, worker_id="hb-test")
    thread, stop = worker._attempt_heartbeat_thread("attempt-1", "tok")
    try:
        time.sleep(2.4)  # interval = max(1, 1//3) = 1s -> ~2 beats
    finally:
        stop.set()
    thread.join(timeout=3)
    assert beats and beats[0] == "attempt-1"
    assert not thread.is_alive()


def test_payload_for_premium_enables_cot_planner_and_adg(orch) -> None:
    # Premium (use_cot) jobs must forward thinking + planner LM path; ADG comes from
    # resolved_controls. FakeAdapter.build_payload echoes kwargs, so we assert them.
    from types import SimpleNamespace
    worker = _worker(orch, FakeAdapter([]))
    job = SimpleNamespace(
        request_json={
            "music_description": "x", "instrumental": False, "duration_seconds": 240, "controls": {},
            "_admission": {
                "use_cot": True, "planner_model": "acestep-5Hz-lm-1.7B",
                "resolved_controls": {"inference_steps": 100, "guidance_scale": 7.0, "shift": 3.0, "use_adg": True},
            },
        },
        lyrics="la la", owner_id="usr_x",
    )
    payload = worker._payload_for(job)
    assert payload["thinking"] is True
    assert payload["lm_model_path"] == "acestep-5Hz-lm-1.7B"
    assert payload["controls"]["use_adg"] is True


def test_payload_for_turbo_stays_dit_only(orch) -> None:
    # turbo-fast-v1 sets use_cot False -> thinking forwarded False (adapter DiT-only default).
    from types import SimpleNamespace
    worker = _worker(orch, FakeAdapter([]))
    job = SimpleNamespace(
        request_json={"music_description": "x", "controls": {},
                      "_admission": {"use_cot": False, "planner_model": None, "resolved_controls": {"inference_steps": 8}}},
        lyrics=None, owner_id="usr_x",
    )
    payload = worker._payload_for(job)
    assert payload["thinking"] is False
    # turbo has no planner LM -> None (build_payload omits lm_model_path from the real request)
    assert payload.get("lm_model_path") is None


def test_lora_compatible_guards_2b_lora_on_xl() -> None:
    from app.engine_worker import _lora_compatible
    # 2B-trained mood/artist LoRA must NOT be applied to the 4B XL DiT
    assert _lora_compatible("ace-step-1.5", "acestep-v15-xl-sft") is False
    assert _lora_compatible("ace-step-1.5", "acestep-v15-xl-turbo") is False
    # same-family (2B LoRA on turbo/sft) is fine
    assert _lora_compatible("ace-step-1.5", "acestep-v15-turbo") is True
    assert _lora_compatible("ace-step-1.5", "acestep-v15-sft") is True
    # a genuine XL LoRA on XL is fine; unknown base/target -> allow (no behavior change)
    assert _lora_compatible("acestep-v15-xl-sft", "acestep-v15-xl-sft") is True
    assert _lora_compatible("", "acestep-v15-xl-sft") is True
    assert _lora_compatible("ace-step-1.5", "") is True


def test_upstream_task_recovery_reuses_finished_output(client, orch) -> None:
    """Worker death after submit must not pay for a second inference (R3)."""
    from app.models import JobAttempt

    adapter = FakeAdapter([SubmitResult(task_id="orphan-task"),
                           EngineError("ENGINE_TIMEOUT", "worker vanished")])
    worker = _worker(orch, adapter)
    job_id = submit(client, key="rec-1").json()["job_id"]
    orch.dispatcher.publish_once()
    assert worker.run_once() is True
    with orch.db.session() as session:
        attempt = session.execute(
            select(JobAttempt).where(JobAttempt.job_id == job_id, JobAttempt.attempt_number == 1)
        ).scalar_one()
        assert attempt.upstream_task_id == "orphan-task"
        assert _status(orch.db, job_id) == "queued"  # transient -> requeued
        from app.models import Job, utcnow
        from datetime import timedelta
        job = session.execute(select(Job).where(Job.id == job_id)).scalar_one()
        job.next_retry_at = utcnow() - timedelta(seconds=1)
        session.commit()
    orch.dispatcher.publish_once()

    # Recovery: the engine still knows the task and it finished; no new submit.
    recovered = FakeAdapter([("succeeded", [{"file": "/v1/audio?path=x", "dit_model": "acestep-v15-turbo"}])])
    worker2 = _worker(orch, recovered)
    assert worker2.run_once() is True
    assert recovered.submitted == []
    assert _status(orch.db, job_id) == "succeeded"


def test_upstream_task_unknown_falls_back_to_submit(client, orch) -> None:
    from app.models import Job, JobAttempt, utcnow
    from datetime import timedelta

    adapter = FakeAdapter([SubmitResult(task_id="gone-task"),
                           EngineError("ENGINE_TIMEOUT", "died")])
    worker = _worker(orch, adapter)
    job_id = submit(client, key="rec-2").json()["job_id"]
    orch.dispatcher.publish_once()
    worker.run_once()
    with orch.db.session() as session:
        job = session.execute(select(Job).where(Job.id == job_id)).scalar_one()
        job.next_retry_at = utcnow() - timedelta(seconds=1)
        session.commit()
    orch.dispatcher.publish_once()

    # Engine restarted: the old task is unknown -> poll raises -> submit fresh.
    fresh = FakeAdapter([EngineError("ENGINE_NOT_FOUND", "unknown"),
                         SubmitResult(task_id="fresh-task"),
                         ("succeeded", [{"file": "/v1/audio?path=y", "dit_model": "acestep-v15-turbo"}])])
    worker2 = _worker(orch, fresh)
    assert worker2.run_once() is True
    assert len(fresh.submitted) == 1
    assert _status(orch.db, job_id) == "succeeded"


def test_unhealthy_cooldown_defers_claims(client, orch) -> None:
    """R5: a quarantined worker must not keep claiming ordinary jobs."""
    adapter = FakeAdapter([SubmitResult(task_id="t")])
    worker = _worker(orch, adapter)
    worker._mark_unhealthy("ENGINE_OOM", "CUDA out of memory")
    submit(client, key="q-1")
    orch.dispatcher.publish_once()
    assert worker.run_once() is False
    assert orch.queue.depth("oal:queue:ace-step-1.5") == 1
