"""ACE-Step engine worker: consumes queued jobs against the upstream server.

Runs as an isolated process (separate image/venv from the API in deployment);
the API never loads model weights. Polling doubles as the lease heartbeat.
"""

from __future__ import annotations

import logging
import socket
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
    ) -> None:
        self.db = db
        self.queue = queue
        self.storage = storage
        self.adapter = adapter
        self.settings = settings
        self.worker_id = worker_id or f"acestep-{socket.gethostname()}-{os.getpid()}"
        self.queue_name = queue_name or RedisQueue.queue_name("ace-step-1.5")
        self._stop = False

    def register(self) -> None:
        with self.db.session() as session:
            worker = session.get(Worker, self.worker_id)
            if worker is None:
                session.add(Worker(id=self.worker_id, kind="acestep"))
            else:
                worker.last_heartbeat = utcnow()
            session.commit()

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
        job_id = self.queue.receive(self.queue_name, self.settings.worker_brpop_timeout_seconds)
        if job_id is None:
            self.register()
            return False
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
            append_event(session, claimed_job, "stage", "running", stage="submitting", attempt_id=attempt_id)
            session.commit()

        profile_path = self._materialize_adapter(profile_artifacts) if profile_artifacts else None
        if profile_path:
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
        while not self._stop:
            try:
                self.run_once()
            except Exception:
                log.exception("engine worker iteration failed")
                time.sleep(2)

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
    return EngineWorker(db, queue, storage, adapter, settings)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    worker = build_engine_worker()
    print(f"ace-step engine worker {worker.worker_id} consuming {worker.queue_name}")
    try:
        worker.run_forever()
    except KeyboardInterrupt:
        worker.stop()
