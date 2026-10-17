"""Training/evaluation worker (milestone 5).

Consumes the dedicated training and evaluation queues (separate from GPU
inference delivery). Training: materialize the frozen dataset, preprocess,
LoRA-optimize within the recorded budget, export the adapter and register a
candidate profile version. Evaluation: generate fixed-prompt samples with the
candidate loaded and with the base model, and record measurements.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import time
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from .config import Settings, get_settings
from .db import Db
from .engine_acestep import AceStepAdapter, EngineError
from .models import (
    ArtistProfileVersion,
    Asset,
    DatasetTrack,
    DatasetVersion,
    Evaluation,
    TrainingRun,
    Worker,
    new_uuid,
    utcnow,
)
from .orchestration import (
    append_event,
    cancel_attempt,
    claim_attempt,
    fail_attempt,
    get_job_by_id,
    heartbeat,
    is_cancelling,
    set_job_stage,
)
from .queue import RedisQueue, build_redis
from .storage import Storage, build_storage
from .training_acestep import AceStepTrainingAdapter
from .worker import InvalidArtifact, validate_wav

log = logging.getLogger("oal.training_worker")


class TrainingWorker:
    def __init__(
        self,
        db: Db,
        queue: RedisQueue,
        storage: Storage,
        settings: Settings,
        adapter: AceStepTrainingAdapter,
        gen_adapter: AceStepAdapter,
        worker_id: str | None = None,
    ) -> None:
        self.db = db
        self.queue = queue
        self.storage = storage
        self.settings = settings
        self.adapter = adapter
        self.gen_adapter = gen_adapter
        self.worker_id = worker_id or f"training-{socket.gethostname()}-{os.getpid()}"
        self.queues = [
            RedisQueue.queue_name(settings.train_queue_model_id),
            RedisQueue.queue_name(settings.evaluate_queue_model_id),
        ]
        self._stop = False

    def register(self) -> None:
        with self.db.session() as session:
            worker = session.get(Worker, self.worker_id)
            if worker is None:
                session.add(Worker(id=self.worker_id, kind="training"))
            else:
                worker.last_heartbeat = utcnow()
            session.commit()

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

    def run_once(self) -> bool:
        if self._draining():
            self.register()
            time.sleep(2)
            return False
        received = self.queue.receive(self.queues, self.settings.worker_brpop_timeout_seconds)
        if received is None:
            self.register()
            return False
        job_id = received
        claim = claim_attempt(self.db, job_id, self.worker_id)
        if claim is None:
            return True
        claimed_job, attempt_id, lease_token = claim
        with self.db.session() as session:
            job = get_job_by_id(session, claimed_job)
            operation = job.operation
        try:
            if operation == "artist.train":
                self._train(claimed_job, attempt_id, lease_token)
            else:
                self._evaluate(claimed_job, attempt_id, lease_token)
        except EngineError as exc:
            fail_attempt(self.db, self.settings, claimed_job, attempt_id, lease_token, exc.code, exc.message)
        except Exception as exc:
            log.exception("training iteration failed")
            fail_attempt(self.db, self.settings, claimed_job, attempt_id, lease_token, "TRAINING_FAILED", str(exc)[:300])
        return True

    # -- training --------------------------------------------------------------

    def _ensure_engine_ready(self, on_wait=None) -> None:
        """Load the model, waiting for the engine worker to bring the server up.

        The co-located ACE-Step server is owned by the engine worker and may be
        idle-stopped; the engine worker starts it when it sees queued training
        work, so retry until /v1/init answers. ``on_wait`` keeps the job lease
        alive while the engine cold-starts.
        """
        deadline = time.monotonic() + 600
        while True:
            try:
                self.adapter.ensure_model(self.settings.acestep_model)
                return
            except Exception as exc:
                if time.monotonic() >= deadline:
                    raise
                if on_wait is not None:
                    on_wait()
                log.info("engine not ready for training (%s); waiting", exc)
                time.sleep(5)

    def _train(self, job_id: str, attempt_id: str, lease_token: str) -> None:
        with self.db.session() as session:
            job = get_job_by_id(session, job_id)
            request = dict(job.request_json)
            run = session.execute(
                select(TrainingRun).where(TrainingRun.job_id == job.id)
            ).scalar_one_or_none()
            dataset_version = session.get(DatasetVersion, request["dataset_version_id"])
            track_rows = list(session.execute(
                select(DatasetTrack).where(DatasetTrack.dataset_id == dataset_version.dataset_id)
            ).scalars())
            assets = {t.asset_id: session.get(Asset, t.asset_id) for t in track_rows}
            run_id = run.id if run is not None else None
            budget = dict(run.budget_json) if run is not None else {}
            hyperparams = dict(run.hyperparams_json) if run is not None else {}
            seed = run.seed if run is not None and run.seed is not None else 42
            base_model_id = request.get("base_model_id") or "ace-step-1.5"
            recipe = request.get("recipe_revision", self.settings.train_recipe_revision)
            dataset_version_id = dataset_version.id
        if run_id is None:
            fail_attempt(self.db, self.settings, job_id, attempt_id, lease_token, "TRAINING_RUN_MISSING", "Training run record missing.")
            return

        max_wall = int(budget.get("max_wall_seconds", self.settings.train_max_wall_seconds))
        epochs = int(hyperparams.get("train_epochs", budget.get("max_epochs", 10)))

        workdir = Path(self.settings.train_workdir).resolve() / job_id
        dataset_dir = workdir / "dataset"
        dataset_dir.mkdir(parents=True, exist_ok=True)
        all_instrumental = True
        for index, track in enumerate(sorted(track_rows, key=lambda t: t.created_at)):
            asset = assets[track.asset_id]
            body = self.storage.get(asset.storage_key).body
            (dataset_dir / f"track{index}.wav").write_bytes(body)
            if track.lyrics and track.lyrics.strip():
                all_instrumental = False
                (dataset_dir / f"track{index}.lyrics.txt").write_text(track.lyrics, encoding="utf-8")
            caption = (track.labels_json or {}).get("caption", "custom artist track")
            (dataset_dir / f"track{index}.json").write_text(json.dumps({"caption": caption}), encoding="utf-8")

        with self.db.session() as session:
            run_row = session.get(TrainingRun, run_id)
            run_row.status = "running"
            run_row.worker_id = self.worker_id
            session.commit()

        set_job_stage(self.db, job_id, "preparing dataset")
        self._ensure_engine_ready(lambda: heartbeat(self.db, attempt_id, lease_token))
        self.adapter.scan_dataset(str(dataset_dir), f"oal-{job_id[:8]}", all_instrumental)
        self.adapter.preprocess(str(workdir / "tensors"))
        heartbeat(self.db, attempt_id, lease_token)
        self.adapter.start_training(
            str(workdir / "tensors"), str(workdir / "lora"), epochs=epochs, seed=seed,
            hyperparams={k: v for k, v in hyperparams.items() if k != "train_epochs"},
        )

        deadline = time.monotonic() + max_wall
        poll = self.settings.train_poll_seconds
        status: dict = {}
        while True:
            if is_cancelling(self.db, job_id):
                self.adapter.stop_training()
                cancel_attempt(self.db, job_id, attempt_id, lease_token)
                return
            status = self.adapter.training_status()
            heartbeat(self.db, attempt_id, lease_token)
            done_epochs = int(status.get("current_epoch", 0) or 0)
            set_job_stage(
                self.db, job_id, "training",
                round(min(0.99, done_epochs / max(1, epochs)), 2),
            )
            if not status.get("is_training", False):
                break
            if time.monotonic() > deadline:
                self.adapter.stop_training()
                fail_attempt(self.db, self.settings, job_id, attempt_id, lease_token, "TRAINING_TIMEOUT",
                             "Training exceeded the wall-clock budget.")
                return
            time.sleep(poll)

        if status.get("error"):
            with self.db.session() as session:
                run_row = session.get(TrainingRun, run_id)
                run_row.status = "failed"
                session.commit()
            fail_attempt(self.db, self.settings, job_id, attempt_id, lease_token, "TRAINING_FAILED",
                         str(status["error"])[:300])
            return

        set_job_stage(self.db, job_id, "exporting adapter", 0.97)
        export = self.adapter.export(str(workdir / "lora"), str(workdir / "adapter"))
        adapter_path = self._resolve_adapter_dir(export.get("export_path", str(workdir / "adapter")))
        self._load_fresh(adapter_path)
        loadable = True
        try:
            self.adapter.unload_lora()
        except EngineError:
            pass

        # Persist the exported adapter to durable object storage so an
        # ephemeral node can lose its local copy and any node can load it.
        version_id = new_uuid()
        adapter_prefix = f"owners/{job.owner_id}/adapters/{version_id}"
        adapter_files = sorted(p.name for p in Path(adapter_path).iterdir() if p.is_file())
        for name in adapter_files:
            self.storage.put(f"{adapter_prefix}/{name}", (Path(adapter_path) / name).read_bytes())

        history = status.get("loss_history") or []
        metrics = {
            "steps": status.get("current_step", 0),
            "epochs_completed": status.get("current_epoch", 0),
            "final_loss": history[-1]["loss"] if history else status.get("current_loss"),
            "steps_per_second": status.get("steps_per_second", 0.0),
            "adapter_loadable": loadable,
        }
        from .registry import MODEL_RELEASES

        release = MODEL_RELEASES.get(base_model_id)
        with self.db.session() as session:
            version = ArtistProfileVersion(
                id=version_id,
                profile_id=request["profile_id"],
                owner_id=job.owner_id,
                mechanism="fine_tuned_adapter",
                base_model_id=base_model_id,
                base_revision=release.revision if release else "unknown",
                recipe_revision=recipe,
                dataset_version_id=dataset_version_id,
                artifacts_json={"adapter_path": adapter_path, "tensor_dir": str(workdir / "tensors"),
                                "dataset_dir": str(dataset_dir), "hardware": socket.gethostname(),
                                "adapter_loadable": loadable, "adapter_object_prefix": adapter_prefix,
                                "adapter_files": adapter_files},
                evaluation_status="none",
                state="candidate",
            )
            session.add(version)
            run_row = session.get(TrainingRun, run_id)
            run_row.status = "succeeded"
            run_row.profile_version_id = version.id
            run_row.metrics_json = metrics
            run_row.hardware = socket.gethostname()
            job_row = get_job_by_id(session, job_id)
            job_row.status = "succeeded"
            job_row.stage = "done"
            job_row.progress = 1.0
            job_row.progress_source = "training"
            job_row.finished_at = utcnow()
            append_event(session, job_id, "succeeded", "succeeded", stage="done", progress=1.0, attempt_id=attempt_id)
            session.commit()

    def _load_fresh(self, adapter_path: str) -> None:
        """Upstream keeps adapter names registered after unload; use a unique
        name per load so repeated candidate loads cannot collide."""
        try:
            self.adapter.unload_lora()
        except EngineError:
            pass
        self.adapter.load_lora(adapter_path, adapter_name=f"oal-{uuid4().hex[:8]}")

    @staticmethod
    def _resolve_adapter_dir(export_path: str) -> str:
        """The upstream trainer may nest the PEFT directory one level deeper."""
        root = Path(export_path)
        if (root / "adapter_config.json").is_file():
            return str(root)
        nested = root / "adapter"
        if (nested / "adapter_config.json").is_file():
            return str(nested)
        raise EngineError("ARTIFACT_INVALID", f"No PEFT adapter found under {export_path}.")

    # -- evaluation --------------------------------------------------------------

    def _evaluate(self, job_id: str, attempt_id: str, lease_token: str) -> None:
        with self.db.session() as session:
            job = get_job_by_id(session, job_id)
            request = dict(job.request_json)
            evaluation = session.execute(
                select(Evaluation).where(Evaluation.job_id == job.id)
            ).scalar_one_or_none()
            version = session.get(ArtistProfileVersion, evaluation.profile_version_id) if evaluation else None
            owner_ok = version is not None and version.owner_id == job.owner_id
            adapter_path = (version.artifacts_json or {}).get("adapter_path") if version else None
            prompts = request.get("prompts", [])
            evaluation_id = evaluation.id if evaluation else None
            version_id = version.id if version else None
        if not owner_ok or adapter_path is None or evaluation_id is None:
            fail_attempt(self.db, self.settings, job_id, attempt_id, lease_token, "EVALUATION_SOURCE_MISSING",
                         "Profile version or adapter artifact unavailable.")
            return

        measurements: dict = {}
        self._load_fresh(adapter_path)
        try:
            for index, prompt in enumerate(prompts):
                if is_cancelling(self.db, job_id):
                    cancel_attempt(self.db, job_id, attempt_id, lease_token)
                    return
                self.adapter.set_use_lora(True)
                candidate = self._generate(prompt, seed=1234 + index)
                self.adapter.set_use_lora(False)
                base = self._generate(prompt, seed=1234 + index)
                measurements[f"prompt_{index}"] = {"candidate": candidate, "base": base}
                heartbeat(self.db, attempt_id, lease_token)
        finally:
            try:
                self.adapter.unload_lora()
            except EngineError:
                pass

        with self.db.session() as session:
            evaluation_row = session.get(Evaluation, evaluation_id)
            evaluation_row.measurements_json = measurements
            version_row = session.get(ArtistProfileVersion, version_id)
            version_row.evaluation_status = "measured"
            job_row = get_job_by_id(session, job_id)
            job_row.status = "succeeded"
            job_row.stage = "done"
            job_row.progress = 1.0
            job_row.progress_source = "evaluation"
            job_row.finished_at = utcnow()
            append_event(session, job_id, "succeeded", "succeeded", stage="done", progress=1.0, attempt_id=attempt_id)
            session.commit()

    def _generate(self, prompt: str, seed: int) -> dict:
        payload = self.gen_adapter.build_payload(
            music_description=prompt, lyrics=None, instrumental=True, seed=seed, duration_seconds=12
        )
        submit = self.gen_adapter.submit(payload)
        deadline = time.monotonic() + self.settings.engine_timeout_seconds
        while True:
            state, result = self.gen_adapter.poll(submit.task_id)
            if state == "succeeded":
                break
            if state == "failed":
                raise EngineError("ENGINE_GENERATION_FAILED", "Evaluation generation failed.")
            if time.monotonic() > deadline:
                raise EngineError("ENGINE_TIMEOUT", "Evaluation generation timed out.")
            time.sleep(self.settings.engine_poll_seconds)
        file_url = (result or {}).get("file")
        if not file_url:
            raise EngineError("ENGINE_NO_AUDIO", "Evaluation generation returned no audio.")
        body = self.gen_adapter.download(file_url)
        rate, channels, duration = validate_wav(body, self.settings.max_artifact_bytes)
        return {"sample_rate": rate, "channels": channels, "duration_seconds": round(duration, 3),
                "bytes": len(body)}

    def run_forever(self) -> None:
        self.register()
        while not self._stop:
            try:
                self.run_once()
            except Exception:
                log.exception("training worker iteration failed")
                time.sleep(2)

    def stop(self) -> None:
        self._stop = True


def build_training_worker() -> TrainingWorker:
    import httpx

    from .engine_acestep import RequestsTransport

    settings = get_settings()
    db = Db(settings.database_url)
    queue = RedisQueue(build_redis(settings.redis_url))
    storage = build_storage(settings)
    transport = RequestsTransport(
        settings.acestep_base_url,
        api_key=settings.acestep_api_key or None,
        timeout=settings.train_http_timeout_seconds,
    )
    gen_transport = RequestsTransport(
        settings.acestep_base_url,
        api_key=settings.acestep_api_key or None,
        timeout=settings.engine_http_timeout_seconds,
    )
    return TrainingWorker(
        db, queue, storage, settings,
        adapter=AceStepTrainingAdapter(transport),
        gen_adapter=AceStepAdapter(gen_transport, model=settings.acestep_model, thinking=settings.acestep_thinking),
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    worker = build_training_worker()
    print(f"training worker {worker.worker_id} consuming {worker.queues}")
    try:
        worker.run_forever()
    except KeyboardInterrupt:
        worker.stop()
