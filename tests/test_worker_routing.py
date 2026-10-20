"""Phase 3 Stage E: worker capability registration + per-job model routing."""

from __future__ import annotations

from app.engine_acestep import SubmitResult
from app.engine_worker import AceStepProcess, EngineWorker
from app.models import WorkerCapability
from app.worker import generate_fixture_wav
from sqlalchemy import select


class FakeAdapter:
    model = "acestep-v15-turbo"

    def build_payload(self, **kwargs):
        return dict(kwargs)

    def submit(self, payload):
        return SubmitResult(task_id="t")

    def poll(self, task_id):
        return ("succeeded", [{"file": "/v1/audio?path=x"}])

    def download(self, file_url):
        return generate_fixture_wav("abc", 7, 2)


def _w(orch, adapter=None, process=None) -> EngineWorker:
    return EngineWorker(orch.db, orch.queue, orch.storage, adapter or FakeAdapter(), orch.settings,
                        worker_id="route-test", engine_process=process)


def test_registers_capabilities_gated_by_installed_checkpoints(orch) -> None:
    orch.settings.acestep_checkpoints_dir = "/nonexistent-checkpoints"
    _w(orch).register()
    with orch.db.session() as session:
        caps = {c.model_selection: c for c in session.execute(
            select(WorkerCapability).where(WorkerCapability.worker_id == "route-test")).scalars()}
    assert caps["ace-step-1.5-turbo"].enabled is True
    # sft profile is "available" in the catalog but its checkpoint isn't installed here
    assert caps["ace-step-1.5-sft"].enabled is False
    # xl/merge are unconfigured -> never advertised
    assert "ace-step-1.5-xl-sft" not in caps
    assert "ace-step-1.5-merge-sft-turbo" not in caps


def test_sft_capability_enabled_when_checkpoint_present(orch, tmp_path) -> None:
    (tmp_path / "acestep-v15-sft").mkdir()
    orch.settings.acestep_checkpoints_dir = str(tmp_path)
    _w(orch).register()
    with orch.db.session() as session:
        cap = session.execute(select(WorkerCapability).where(
            WorkerCapability.worker_id == "route-test",
            WorkerCapability.model_selection == "ace-step-1.5-sft")).scalar_one()
    assert cap.enabled is True


def test_target_engine_model_selection(orch) -> None:
    worker = _w(orch)
    default_model = orch.settings.acestep_model
    assert worker._target_engine_model({}) == default_model
    assert worker._target_engine_model({"_admission": {"family": "turbo", "engine_model": "acestep-v15-turbo"}}) == default_model
    assert worker._target_engine_model({"_admission": {"family": "sft", "engine_model": "acestep-v15-sft"}}) == "acestep-v15-sft"


def test_premium_job_swaps_engine_to_requested_model(orch) -> None:
    # Turbo job uses the default model with no swap; an sft admission swaps the engine.
    class RecordingProcess(AceStepProcess):
        def __init__(self):
            super().__init__(cwd="/", cmd=["true"], base_url="http://x")
            self.calls: list = []

        def is_running(self):
            return self.model is not None

        def _healthy(self):
            return True

        def ensure_running(self, model=None):
            self.calls.append(model)
            self.model = model

        def stop(self):
            pass

    proc = RecordingProcess()
    worker = _w(orch, process=proc)
    # enqueue a job whose admission targets sft
    import hashlib
    from app.models import Job, new_uuid
    req = {"operation": "music.generate", "model_id": "ace-step-1.5", "music_description": "x",
           "instrumental": True, "outputs": ["mix_wav"],
           "_admission": {"family": "sft", "engine_model": "acestep-v15-sft", "model_selection": "ace-step-1.5-sft",
                          "execution_profile_id": "sft-quality-v1"}}
    digest = hashlib.sha256(b"routejob").hexdigest()
    with orch.db.session() as session:
        session.add(Job(id=new_uuid(), owner_id="usr_route", operation="music.generate",
                        model_id="ace-step-1.5", model_revision="r", status="queued",
                        request_json=req, request_hash=digest, idempotency_key="k"))
        session.commit()
        job_id = session.execute(select(Job).where(Job.request_hash == digest)).scalar_one().id
    orch.queue.publish(worker.queue_name, job_id)
    worker.run_once()
    # The engine was asked to ensure the sft model.
    assert "acestep-v15-sft" in proc.calls
