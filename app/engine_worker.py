"""ACE-Step engine worker: consumes queued jobs against the upstream server.

Runs as an isolated process (separate image/venv from the API in deployment);
the API never loads model weights. Polling doubles as the lease heartbeat.
"""

from __future__ import annotations

import logging
import shlex
import signal
import socket
import subprocess
import threading
import time
import os
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from .config import Settings, get_settings
from .db import Db
from .engine_acestep import AceStepAdapter, EngineError, RequestsTransport
from .models import Job, Worker, utcnow
from .orchestration import (
    append_event,
    claim_attempt,
    complete_attempt,
    fail_attempt,
    get_job_by_id,
    heartbeat,
    is_cancelling,
    set_job_stage,
)
from .queue import RedisQueue, build_redis
from .storage import Storage, build_storage
from .worker import InvalidArtifact, validate_wav

log = logging.getLogger("oal.engine_worker")


class AceStepProcess:
    """Owns the co-located ACE-Step server subprocess.

    The worker starts the server lazily on the first job and stops it when idle,
    so an idle worker holds neither the GPU nor host RAM. The subprocess runs in
    its own session so ``stop`` can signal the whole group (uv + its python
    child) and reliably release CUDA memory.
    """

    def __init__(
        self,
        cwd: str,
        cmd: list[str],
        base_url: str,
        api_key: str | None = None,
        start_timeout: float = 240.0,
        poll: float = 2.0,
    ) -> None:
        self.cwd = cwd
        self.cmd = cmd
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.start_timeout = start_timeout
        self.poll = poll
        self.proc: subprocess.Popen | None = None
        self.model: str | None = None

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _healthy(self) -> bool:
        import httpx

        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            return httpx.get(f"{self.base_url}/health", headers=headers, timeout=5.0).status_code == 200
        except Exception:
            return False

    def ensure_running(self, model: str | None = None) -> None:
        # Only one heavy engine is resident at a time: a model change stops the
        # current server (freeing CUDA memory via process exit) before starting
        # the requested checkpoint. Passing None keeps the currently loaded model.
        if model and self.is_running() and self.model and model != self.model:
            log.info("engine model swap %s -> %s (stopping current to free GPU/RAM)", self.model, model)
            self.stop()
        if self.is_running() and self._healthy():
            if model:
                self.model = model
            return
        if not self.is_running():
            if model:
                os.environ["ACESTEP_CONFIG_PATH"] = model
            log.info("starting ACE-Step server: %s (cwd=%s, model=%s)", " ".join(self.cmd), self.cwd, model or self.model)
            self.proc = subprocess.Popen(self.cmd, cwd=self.cwd, start_new_session=True)
            if model:
                self.model = model
        deadline = time.monotonic() + self.start_timeout
        while time.monotonic() < deadline:
            if self._healthy():
                log.info("ACE-Step server ready (model=%s)", self.model)
                return
            if self.proc is not None and self.proc.poll() is not None:
                rc = self.proc.returncode
                self.proc = None
                self.model = None
                raise EngineError("ENGINE_START_FAILED", f"ACE-Step server exited (code {rc}).")
            time.sleep(self.poll)
        self.stop()
        raise EngineError("ENGINE_START_TIMEOUT", "ACE-Step server did not become healthy in time.")

    def stop(self) -> None:
        proc = self.proc
        self.proc = None
        if proc is None or proc.poll() is not None:
            return
        log.info("stopping ACE-Step server (pid %s)", proc.pid)
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass


def _asset_ext(mime: str) -> str:
    return {
        "audio/wav": ".wav",
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/flac": ".flac",
        "audio/ogg": ".ogg",
        "audio/opus": ".opus",
    }.get((mime or "").lower(), ".wav")


def _is_oom_message(message: str | None) -> bool:
    text = (message or "").lower()
    return "out of memory" in text or "oom" in text or "cuda oom" in text


def _gpu_telemetry() -> tuple[int, int, int] | None:
    """Read (util%, used MB, total MB) for the device this worker uses."""
    import subprocess

    device = os.environ.get("ACESTEP_DEVICE", "cuda:0")
    gpu_index = device.split(":")[-1] if ":" in device else "0"
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                f"--id={gpu_index}",
                "--query-gpu=utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        util, used, total = (int(part) for part in out.stdout.strip().split(","))
        return util, used, total
    except Exception:
        return None


class EngineWorker:
    def __init__(
        self,
        db: Db,
        queue: RedisQueue,
        storage: Storage,
        adapter: AceStepAdapter,
        settings: Settings,
        worker_id: str | None = None,
        queue_name: str | None = None,
        engine_process: "AceStepProcess | None" = None,
    ) -> None:
        self.db = db
        self.queue = queue
        self.storage = storage
        self.adapter = adapter
        self.settings = settings
        self.worker_id = worker_id or settings.worker_id or f"acestep-{socket.gethostname()}-{os.getpid()}"
        self.queue_name = queue_name or RedisQueue.queue_name("ace-step-1.5")
        # Baseline tier drains the main queue first (then helps burst when idle);
        # burst tier (Vast) only ever drains the overflow queue, so it can never
        # steal a job the always-on baseline could take.
        self.receive_queues = (
            [self.queue_name, RedisQueue.burst_name(self.queue_name)]
            if settings.worker_tier == "baseline"
            else [RedisQueue.burst_name(self.queue_name)]
        )
        self.engine_process = engine_process
        self._stop = False
        self._last_activity = time.monotonic()
        self._caps_registered = False

    def register(self) -> None:
        telemetry = _gpu_telemetry()
        with self.db.session() as session:
            worker = session.get(Worker, self.worker_id)
            if worker is None:
                worker = Worker(id=self.worker_id, kind="acestep")
                session.add(worker)
            worker.last_heartbeat = utcnow()
            if telemetry is not None:
                worker.gpu_util, worker.vram_used_mb, worker.vram_total_mb = telemetry
            session.commit()
        if not self._caps_registered:
            try:
                self._register_capabilities()
                self._caps_registered = True
            except Exception:
                log.exception("worker capability registration failed")

    def _mark_unhealthy(self, code: str, message: str) -> None:
        cooldown = max(0.0, float(self.settings.worker_unhealthy_cooldown_seconds))
        until = utcnow() + timedelta(seconds=cooldown) if cooldown else utcnow()
        try:
            with self.db.session() as session:
                worker = session.get(Worker, self.worker_id)
                if worker is None:
                    worker = Worker(id=self.worker_id, kind="acestep")
                    session.add(worker)
                worker.last_error = f"{code}: {message}"[:300]
                worker.unhealthy_until = until
                session.commit()
        except Exception:
            log.exception("could not mark worker %s unhealthy", self.worker_id)

    def _touch_heartbeat(self) -> None:
        path = self.settings.worker_heartbeat_file
        if not path:
            return
        try:
            with open(path, "w") as f:
                f.write(str(time.time()))
        except OSError:
            log.debug("could not write heartbeat file %s", path)

    def _heartbeat_loop(self) -> None:
        while not self._stop:
            self._touch_heartbeat()
            time.sleep(5)

    def _training_busy(self) -> bool:
        """True when training work is queued or a run is active on the server.

        The training worker drives the same co-located ACE-Step server over
        HTTP, so the engine must stay up while training is pending or running.
        """
        import json

        for model_id in (self.settings.train_queue_model_id, self.settings.evaluate_queue_model_id):
            try:
                if self.queue.length(RedisQueue.queue_name(model_id)) > 0:
                    return True
            except Exception:
                pass
        try:
            from sqlalchemy import select

            from .models import TrainingRun

            with self.db.session() as session:
                row = session.execute(
                    select(TrainingRun.id)
                    .where(TrainingRun.status.in_(("queued", "running")))
                    .limit(1)
                ).first()
            if row is not None:
                return True
        except Exception:
            pass
        try:
            data = json.loads(self.adapter.transport.get_bytes("/v1/training/status"))
            return bool(data.get("data", {}).get("is_training"))
        except Exception:
            return False

    def _maybe_stop_engine(self) -> None:
        proc = self.engine_process
        if proc is None or not proc.is_running():
            return
        limit = self.settings.engine_idle_stop_seconds
        if not limit:
            return
        idle = time.monotonic() - self._last_activity
        if idle >= limit:
            log.info("engine idle %ds >= %ss -> stopping to free GPU/RAM", int(idle), int(limit))
            proc.stop()

    def _materialize_adapter(self, artifacts: dict) -> str | None:
        """Resolve a loadable local adapter dir from durable object storage.

        A profile trained on any node is portable: its PEFT files live in the
        bucket, so we cache them under a node-local directory the co-located
        ACE-Step server can read. Falls back to a same-host local path.
        """
        prefix = artifacts.get("adapter_object_prefix")
        files = artifacts.get("adapter_files")
        if prefix and files:
            version_id = prefix.rstrip("/").rsplit("/", 1)[-1]
            cache = Path(self.settings.adapter_cache_dir) / version_id
            cache.mkdir(parents=True, exist_ok=True)
            for name in files:
                target = cache / name
                if not target.is_file():
                    target.write_bytes(self.storage.get(f"{prefix}/{name}").body)
            return str(cache)
        return artifacts.get("adapter_path")

    def _payload_for(self, job: Job) -> dict:
        request = dict(job.request_json)
        return self.adapter.build_payload(
            music_description=request.get("music_description", ""),
            lyrics=job.lyrics,
            instrumental=bool(request.get("instrumental")),
            seed=request.get("seed"),
            duration_seconds=request.get("duration_seconds"),
            controls=request.get("controls"),
            source=self._source_for(job, request),
        )

    def _source_for(self, job: Job, request: dict) -> dict | None:
        """Map owner-validated source/task fields onto upstream REST names.

        Returns None for a plain text2music request so the payload is byte-for-byte
        the pre-Phase-2 shape.
        """
        task_type = request.get("task_type") or "text2music"
        source: dict = {"task_type": task_type}
        src_id = request.get("src_asset_id")
        if src_id:
            path = self._stage_asset(job.owner_id, src_id, "src")
            if path:
                source["src_audio_path"] = path
        ref_id = request.get("reference_asset_id")
        if ref_id:
            path = self._stage_asset(job.owner_id, ref_id, "reference")
            if path:
                source["reference_audio_path"] = path
        for key in (
            "audio_cover_strength",
            "cover_noise_strength",
            "repainting_start",
            "repainting_end",
            "repaint_mode",
            "repaint_strength",
            "chunk_mask_mode",
        ):
            if request.get(key) is not None:
                source[key] = request[key]
        meaningful = task_type != "text2music" or {
            "src_audio_path", "reference_audio_path", "audio_cover_strength",
            "cover_noise_strength", "repainting_start", "repainting_end",
            "repaint_mode", "repaint_strength", "chunk_mask_mode",
        } & source.keys()
        return source if meaningful else None

    def _stage_asset(self, owner_id: str, asset_id: str, role: str) -> str | None:
        """Resolve an owned asset to a node-local path the co-located server can read.

        Ownership is re-checked here (defense in depth); content-hash filename makes
        the staged file immutable + cache-friendly, mirroring _materialize_adapter.
        """
        from .models import Asset

        with self.db.session() as session:
            asset = session.get(Asset, asset_id)
        if asset is None or asset.owner_id != owner_id or asset.deleted_at is not None:
            return None
        target_dir = Path(self.settings.asset_stage_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{role}-{asset.sha256}{_asset_ext(asset.mime)}"
        if not target.is_file():
            target.write_bytes(self.storage.get(asset.storage_key).body)
        return str(target)

    def _draining(self) -> bool:
        """Admin drain flag: stop claiming new jobs (re-checked every 5s)."""
        now = time.monotonic()
        if now - getattr(self, "_drain_checked_at", 0.0) < 5.0:
            return getattr(self, "_drain_flag", False)
        try:
            from sqlalchemy import select

            with self.db.session() as session:
                flag = session.execute(
                    select(Worker.drain).where(Worker.id == self.worker_id)
                ).scalar_one_or_none()
            self._drain_flag = bool(flag)
        except Exception:
            self._drain_flag = False
        self._drain_checked_at = now
        return self._drain_flag

    def _target_engine_model(self, request_json: dict) -> str:
        """Engine checkpoint this job needs. Turbo uses the worker's configured
        default (preserving the live baseline model); premium uses its release."""
        admission = dict((request_json or {}).get("_admission") or {})
        model = admission.get("engine_model")
        family = admission.get("family")
        if not model or family == "turbo":
            return self.settings.acestep_model
        return model

    def _register_capabilities(self) -> None:
        """Advertise which catalog profiles this worker can actually run, based on
        the engine checkpoints installed here. Absent checkpoints stay disabled,
        so premium jobs 503 until provisioned (never a silent Turbo downgrade)."""
        from . import catalog as _catalog
        from .models import WorkerCapability

        ckpt_root = Path(self.settings.acestep_checkpoints_dir)
        with self.db.session() as session:
            for release in _catalog.CATALOG.values():
                for prof in release.profiles:
                    if prof.availability != "available":
                        continue
                    if prof.native_family == "turbo":
                        present = True
                    else:
                        present = (ckpt_root / prof.engine_model).is_dir()
                    existing = session.execute(
                        select(WorkerCapability).where(
                            WorkerCapability.worker_id == self.worker_id,
                            WorkerCapability.model_selection == prof.model_selection,
                            WorkerCapability.execution_profile_id == prof.profile_id,
                        )
                    ).scalar_one_or_none()
                    if existing is None:
                        session.add(WorkerCapability(
                            worker_id=self.worker_id,
                            model_selection=prof.model_selection,
                            execution_profile_id=prof.profile_id,
                            engine_model=prof.engine_model if prof.native_family != "turbo" else self.settings.acestep_model,
                            planner_model=prof.planner_model,
                            tasks_json=list(prof.tasks),
                            max_duration_seconds=prof.max_duration_seconds,
                            enabled=present,
                        ))
                    else:
                        existing.enabled = present
                        existing.tasks_json = list(prof.tasks)
                        existing.max_duration_seconds = prof.max_duration_seconds
            session.commit()

    def run_once(self) -> bool:
        if self._draining():
            self.register()
            self._touch_heartbeat()
            time.sleep(2)
            return False
        job_id = self.queue.receive(self.receive_queues, self.settings.worker_brpop_timeout_seconds)
        if job_id is None:
            self.register()
            self._touch_heartbeat()
            if self._training_busy():
                self._last_activity = time.monotonic()
                if self.engine_process is not None:
                    try:
                        self.engine_process.ensure_running()
                    except EngineError as exc:
                        log.warning("engine start failed for training (%s)", exc.code)
                        self._mark_unhealthy(exc.code, exc.message)
            else:
                self._maybe_stop_engine()
            return False
        self._last_activity = time.monotonic()
        claim = claim_attempt(self.db, job_id, self.worker_id)
        if claim is None:
            return True
        claimed_job, attempt_id, lease_token = claim
        with self.db.session() as session:
            _claimed = get_job_by_id(session, claimed_job)
            target_model = self._target_engine_model(dict(_claimed.request_json or {}))
        # Start/swap the engine to the job's model AFTER claiming, so only the
        # requested checkpoint is ever resident (serialized GPU ownership).
        if self.engine_process is not None:
            try:
                self.engine_process.ensure_running(model=target_model)
            except EngineError as exc:
                log.warning("engine start/swap failed for job %s (%s); requeueing", job_id, exc.code)
                self._mark_unhealthy(exc.code, exc.message)
                self._requeue(claimed_job, attempt_id, lease_token)
                time.sleep(5)
                return True
        if target_model:
            self.adapter.model = target_model
        with self.db.session() as session:
            job = get_job_by_id(session, claimed_job)
            payload = self._payload_for(job)
            profile_artifacts: dict | None = None
            profile_version_id = dict(job.request_json).get("artist_profile_version_id")
            if profile_version_id:
                from .models import ArtistProfileVersion

                version = session.get(ArtistProfileVersion, profile_version_id)
                if version is not None:
                    profile_artifacts = dict(version.artifacts_json or {})
            lora_artifacts: dict | None = None
            lora_id = dict(job.request_json).get("lora_id")
            if lora_id:
                from .models import Lora

                lora = session.get(Lora, lora_id)
                if lora is not None and lora.state == "active" and lora.storage_prefix and lora.files_json:
                    lora_artifacts = {
                        "adapter_object_prefix": lora.storage_prefix,
                        "adapter_files": list(lora.files_json),
                    }
                    # M14e: the LoRA's tags act as style keywords guiding generation.
                    extra = ", ".join(t for t in (lora.tags_json or []) if t)
                    if extra:
                        payload["prompt"] = f"{payload.get('prompt', '')}, {extra}".strip(", ")
            append_event(session, claimed_job, "stage", "running", stage="submitting", attempt_id=attempt_id)
            session.commit()
        set_job_stage(self.db, claimed_job, "preparing model")

        adapter_artifacts = lora_artifacts or profile_artifacts
        profile_path = self._materialize_adapter(adapter_artifacts) if adapter_artifacts else None
        if profile_path:
            self.adapter.ensure_model()
            try:
                self.adapter.unload_lora()
            except EngineError:
                pass
            self.adapter.load_lora(profile_path, adapter_name=f"oal-{uuid4().hex[:8]}")

        try:
            submit = self.adapter.submit(payload)
        except EngineError as exc:
            if exc.code == "ENGINE_BUSY":
                self._requeue(claimed_job, attempt_id, lease_token)
                return True
            if _is_oom_message(exc.message):
                self._mark_unhealthy(exc.code, exc.message)
            fail_attempt(self.db, self.settings, claimed_job, attempt_id, lease_token, exc.code, exc.message)
            return True

        set_job_stage(self.db, claimed_job, "generating audio")
        try:
            return self._run_generation(claimed_job, attempt_id, lease_token, submit, payload)
        finally:
            if profile_path:
                try:
                    self.adapter.unload_lora()
                except EngineError:
                    log.warning("failed to unload profile adapter after job %s", claimed_job)

    def _run_generation(
        self, claimed_job: str, attempt_id: str, lease_token: str, submit, payload: dict
    ) -> bool:
        deadline = time.monotonic() + self.settings.engine_timeout_seconds
        poll_interval = self.settings.engine_poll_seconds
        while True:
            if is_cancelling(self.db, claimed_job):
                # Upstream cannot be cancelled; discard the late result.
                from .orchestration import cancel_attempt

                cancel_attempt(self.db, claimed_job, attempt_id, lease_token)
                return True
            try:
                state, result = self.adapter.poll(submit.task_id)
            except EngineError as exc:
                if exc.code == "ENGINE_BUSY":
                    state, result = "pending", None
                else:
                    if _is_oom_message(exc.message):
                        self._mark_unhealthy(exc.code, exc.message)
                    fail_attempt(self.db, self.settings, claimed_job, attempt_id, lease_token, exc.code, exc.message)
                    return True
            heartbeat(self.db, attempt_id, lease_token)
            self._touch_heartbeat()
            if state == "failed":
                message = getattr(self.adapter, "last_error", "") or "Upstream generation failed."
                if _is_oom_message(message):
                    self._mark_unhealthy("ENGINE_OOM", message)
                fail_attempt(
                    self.db, self.settings, claimed_job, attempt_id, lease_token,
                    "ENGINE_GENERATION_FAILED", message,
                )
                return True
            if state == "succeeded":
                break
            if time.monotonic() > deadline:
                fail_attempt(
                    self.db, self.settings, claimed_job, attempt_id, lease_token,
                    "ENGINE_TIMEOUT", "Upstream generation exceeded the timeout.",
                )
                return True
            time.sleep(poll_interval)

        results = result or []
        file_urls = [r.get("file") for r in results if r.get("file")]
        if not file_urls:
            fail_attempt(self.db, self.settings, claimed_job, attempt_id, lease_token, "ENGINE_NO_AUDIO", "Upstream returned no audio file.")
            return True
        try:
            artifacts: list[tuple[str, bytes, tuple | None]] = []
            for file_url in file_urls:
                body = self.adapter.download(file_url)
                rate, channels, duration = validate_wav(body, self.settings.max_artifact_bytes)
                artifacts.append(("mix_wav", body, (rate, channels, duration)))
        except (EngineError, InvalidArtifact) as exc:
            code = getattr(exc, "code", "ARTIFACT_INVALID")
            fail_attempt(self.db, self.settings, claimed_job, attempt_id, lease_token, code, str(exc))
            return True

        first_result = results[0] or {}
        engine_version = f"ace-step-1.5/{first_result.get('dit_model', self.adapter.model)}"
        complete_attempt(
            self.db,
            self.storage,
            self.settings,
            claimed_job,
            attempt_id,
            lease_token,
            artifacts,
            synthetic=False,
            engine_version=engine_version,
            engine_payload=payload,
            engine_result={**first_result, "task_id": submit.task_id},
        )
        return True

    def _requeue(self, job_id: str, attempt_id: str, lease_token: str) -> None:
        """Engine busy: release the attempt and requeue without burning budget."""
        from sqlalchemy import delete, select as sa_select, update

        from .models import JobAttempt, OutboxRecord

        with self.db.session() as session:
            held = session.execute(
                sa_select(JobAttempt).where(
                    JobAttempt.id == attempt_id,
                    JobAttempt.lease_token == lease_token,
                    JobAttempt.status == "running",
                )
            ).scalar_one_or_none()
            if held is None:
                session.commit()
                return
            session.execute(delete(JobAttempt).where(JobAttempt.id == attempt_id))
            job = get_job_by_id(session, job_id)
            if job is not None and job.status == "running":
                job.status = "queued"
                job.stage = None
                session.add(OutboxRecord(job_id=job.id, queue=self.queue_name))
                append_event(session, job.id, "deferred", "queued", message="Engine busy; requeued.", attempt_id=attempt_id)
            session.commit()

    def run_forever(self) -> None:
        self.register()
        heartbeat = threading.Thread(target=self._heartbeat_loop, daemon=True)
        heartbeat.start()
        try:
            while not self._stop:
                try:
                    self.run_once()
                except Exception:
                    log.exception("engine worker iteration failed")
                    time.sleep(2)
        finally:
            self._stop = True
            if self.engine_process is not None:
                self.engine_process.stop()

    def stop(self) -> None:
        self._stop = True


def build_engine_worker() -> EngineWorker:
    settings = get_settings()
    db = Db(settings.database_url)
    queue = RedisQueue(build_redis(settings.redis_url))
    storage = build_storage(settings)
    transport = RequestsTransport(
        settings.acestep_base_url,
        api_key=settings.acestep_api_key or None,
        timeout=settings.engine_http_timeout_seconds,
    )
    adapter = AceStepAdapter(transport, model=settings.acestep_model, thinking=settings.acestep_thinking)
    engine_process = None
    if settings.engine_autostart:
        engine_process = AceStepProcess(
            cwd=settings.acestep_cwd,
            cmd=shlex.split(settings.acestep_start_cmd),
            base_url=settings.acestep_base_url,
            api_key=settings.acestep_api_key or None,
            start_timeout=settings.engine_start_timeout_seconds,
        )
    return EngineWorker(db, queue, storage, adapter, settings, engine_process=engine_process)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    worker = build_engine_worker()
    print(f"ace-step engine worker {worker.worker_id} consuming {worker.queue_name}")
    try:
        worker.run_forever()
    except KeyboardInterrupt:
        worker.stop()
