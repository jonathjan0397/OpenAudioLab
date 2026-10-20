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


def test_sft_capability_requires_allowlist_and_checkpoint(orch, tmp_path) -> None:
    (tmp_path / "acestep-v15-sft").mkdir()
    orch.settings.acestep_checkpoints_dir = str(tmp_path)
    # Checkpoint present but NOT allowlisted -> must stay disabled (no silent premium serving).
    orch.settings.premium_profiles_enabled = ""
    _w(orch).register()
    with orch.db.session() as session:
        cap = session.execute(select(WorkerCapability).where(
            WorkerCapability.worker_id == "route-test",
            WorkerCapability.model_selection == "ace-step-1.5-sft")).scalar_one()
    assert cap.enabled is False
    # Allowlisted + present -> enabled.
    orch.settings.premium_profiles_enabled = "sft-quality-v1"
    _w(orch, adapter=FakeAdapter()).register()
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


class _Swapper(AceStepProcess):
    def __init__(self, model):
        super().__init__(cwd="/", cmd=["true"], base_url="http://x")
        self.model = model
        self._alive = True
        self.stops = 0

    def is_running(self):
        return self._alive

    def _healthy(self):
        return True

    def stop(self):
        self.stops += 1
        self._alive = False


def test_ensure_running_swaps_when_model_differs(monkeypatch):
    import app.engine_worker as ew

    started: list = []

    class FakePopen:
        def __init__(self, cmd, **kw):
            started.append(cmd)

    monkeypatch.setattr(ew.subprocess, "Popen", FakePopen)
    proc = _Swapper("acestep-v15-house-turbo")
    proc.ensure_running(model="acestep-v15-sft")
    assert proc.stops == 1  # stopped the current engine
    assert started and proc.model == "acestep-v15-sft"


def test_ensure_running_no_restart_when_model_matches(monkeypatch):
    import app.engine_worker as ew

    started: list = []

    class FakePopen:
        def __init__(self, cmd, **kw):
            started.append(cmd)

    monkeypatch.setattr(ew.subprocess, "Popen", FakePopen)
    proc = _Swapper("acestep-v15-house-turbo")
    proc.ensure_running(model="acestep-v15-house-turbo")
    assert proc.stops == 0 and started == [] and proc.model == "acestep-v15-house-turbo"



def test_premium_vram_floors_are_declared():
    from app import catalog
    xl = catalog.CATALOG["ace-step-1.5-xl-sft"].profiles[0]
    xl_turbo = catalog.CATALOG["ace-step-1.5-xl-turbo"].profiles[0]
    sft = catalog.CATALOG["ace-step-1.5-sft"].profiles[0]
    # XL (4B DiT) loads ~9 GB bf16 and is an upstream 20-24 GB (tier6b) model, so
    # the floor keeps it off small GPUs while still letting the shared 24 GB
    # baseline worker serve it (with the llama-server footprint shrunk).
    assert 10000 <= xl.vram_required_mb <= 20000
    assert 10000 <= xl_turbo.vram_required_mb <= 20000
    # SFT (2B) fits the 24 GB worker.
    assert 0 < sft.vram_required_mb <= 24000


def test_xl_turbo_profile_is_cfg_distilled_and_locked():
    from app import catalog
    # XL-Turbo is CFG-distilled (upstream forces guidance=1.0, rejects CFG/ADG),
    # so it mirrors turbo-fast-v1: 8 steps locked, guidance locked at 1.0, DCW off.
    p = catalog.CATALOG["ace-step-1.5-xl-turbo"].profiles[0]
    assert p.profile_id == "xl-turbo-fast-v1"
    assert p.native_family == "xl"
    assert (p.steps_min, p.steps_max, p.steps_default) == (8, 8, 8)
    assert (p.cfg_min, p.cfg_max, p.cfg_default) == (1.0, 1.0, 1.0)
    assert p.cfg_locked is True
    assert p.dcw_forced_off is True
    assert p.planner_model is None
    assert p.multiplier == 2.00
    assert p.tasks == ("text2music", "cover", "repaint")
    # No operator checkpoint configured in tests -> unconfigured (503), not Turbo.
    assert p.availability == "unconfigured"
    # Schema reflects the locks.
    schema = p.control_schema()
    assert schema["inference_steps"]["const"] == 8
    assert schema["guidance_scale"]["const"] == 1.0 and schema["guidance_scale"]["locked"] is True


def test_xl_sft_profile_uses_xl_family_and_no_planner():
    from app import catalog
    p = catalog.CATALOG["ace-step-1.5-xl-sft"].profiles[0]
    assert p.profile_id == "xl-sft-quality-v1"
    assert p.native_family == "xl"
    assert p.planner_model is None
    assert p.multiplier == 4.00
    assert p.tasks == ("text2music", "cover", "repaint")


def test_xl_multipliers_are_provisional_and_distinct():
    from app import catalog
    turbo = catalog.CATALOG["ace-step-1.5-turbo"].profiles[0]
    xl_turbo = catalog.CATALOG["ace-step-1.5-xl-turbo"].profiles[0]
    xl_sft = catalog.CATALOG["ace-step-1.5-xl-sft"].profiles[0]
    assert turbo.multiplier == 1.0
    assert xl_turbo.multiplier == 2.0
    assert xl_sft.multiplier == 4.0
    # Same takes/compute -> quoted credits scale exactly with the multiplier.
    assert catalog.quoted_credits(xl_turbo, 1) == 2 * catalog.quoted_credits(turbo, 1)
    assert catalog.quoted_credits(xl_sft, 1) == 4 * catalog.quoted_credits(turbo, 1)
