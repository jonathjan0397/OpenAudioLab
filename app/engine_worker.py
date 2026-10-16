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

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _healthy(self) -> bool:
        import httpx

        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            return httpx.get(f"{self.base_url}/health", headers=headers, timeout=5.0).status_code == 200
        except Exception:
            return False

    def ensure_running(self) -> None:
        if self.is_running() and self._healthy():
            return
        if not self.is_running():
            log.info("starting ACE-Step server: %s (cwd=%s)", " ".join(self.cmd), self.cwd)
            self.proc = subprocess.Popen(self.cmd, cwd=self.cwd, start_new_session=True)
        deadline = time.monotonic() + self.start_timeout
        while time.monotonic() < deadline:
            if self._healthy():
                log.info("ACE-Step server ready")
                return
            if self.proc is not None and self.proc.poll() is not None:
                self.proc = None
                raise EngineError("ENGINE_START_FAILED", f"ACE-Step server exited (code {self.proc.returncode if self.proc else '?'}).")
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
        self.worker_id = worker_id or f"acestep-{socket.gethostname()}-{os.getpid()}"
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

    def register(self) -> None:
        with self.db.session() as session:
            worker = session.get(Worker, self.worker_id)
            if worker is None:
                session.add(Worker(id=self.worker_id, kind="acestep"))
            else:
                worker.last_heartbeat = utcnow()
            session.commit()

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
        )

    def run_once(self) -> bool:
        job_id = self.queue.receive(self.receive_queues, self.settings.worker_brpop_timeout_seconds)
        if job_id is None:
            self.register()
            self._touch_heartbeat()
            self._maybe_stop_engine()
            return False
        self._last_activity = time.monotonic()
        if self.engine_process is not None:
            try:
                self.engine_process.ensure_running()
            except EngineError as exc:
                log.warning("engine start failed for job %s (%s); requeueing", job_id, exc.code)
                self.queue.publish(self.receive_queues[0], job_id)
                time.sleep(5)
                return True
        claim = claim_attempt(self.db, job_id, self.worker_id)
        if claim is None:
            return True
        claimed_job, attempt_id, lease_token = claim
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
            append_event(session, claimed_job, "stage", "running", stage="submitting", attempt_id=attempt_id)
            session.commit()

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
            fail_attempt(self.db, self.settings, claimed_job, attempt_id, lease_token, exc.code, exc.message)
            return True

        try:
            return self._run_generation(claimed_job, attempt_id, lease_token, submit)
        finally:
            if profile_path:
                try:
                    self.adapter.unload_lora()
                except EngineError:
                    log.warning("failed to unload profile adapter after job %s", claimed_job)

    def _run_generation(self, claimed_job: str, attempt_id: str, lease_token: str, submit) -> bool:
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
                    fail_attempt(self.db, self.settings, claimed_job, attempt_id, lease_token, exc.code, exc.message)
                    return True
            heartbeat(self.db, attempt_id, lease_token)
            self._touch_heartbeat()
            if state == "failed":
                fail_attempt(
                    self.db, self.settings, claimed_job, attempt_id, lease_token,
                    "ENGINE_GENERATION_FAILED", "Upstream generation failed.",
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

        file_url = (result or {}).get("file")
        if not file_url:
            fail_attempt(self.db, self.settings, claimed_job, attempt_id, lease_token, "ENGINE_NO_AUDIO", "Upstream returned no audio file.")
            return True
        try:
            body = self.adapter.download(file_url)
            rate, channels, duration = validate_wav(body, self.settings.max_artifact_bytes)
        except (EngineError, InvalidArtifact) as exc:
            code = getattr(exc, "code", "ARTIFACT_INVALID")
            fail_attempt(self.db, self.settings, claimed_job, attempt_id, lease_token, code, str(exc))
            return True

        engine_version = f"ace-step-1.5/{(result or {}).get('dit_model', self.adapter.model)}"
        complete_attempt(
            self.db,
            self.storage,
            self.settings,
            claimed_job,
            attempt_id,
            lease_token,
            ("mix_wav", body),
            audio_meta=(rate, channels, duration),
            synthetic=False,
            engine_version=engine_version,
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
