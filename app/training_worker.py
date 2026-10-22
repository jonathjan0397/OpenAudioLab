"""UAIS training/analysis/validation worker.

Consumes the dedicated training queues (separate GPU allocation from
inference). ``voice.train`` materializes a frozen dataset version, preprocess,
LoRA-optimizes within the recorded budget, exports the adapter, load-tests it
and registers a ready VoiceAdapter. ``voice.analyze`` extracts portable voice
identity embeddings. ``voice.validate`` measures generated-vocal similarity
against the artist reference centroid before an adapter is called validated.
Durable records are authoritative; a run is only trained after artifacts are
saved and validated.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import signal
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from .config import Settings, get_settings
from .db import Db
from .engine_acestep import AceStepAdapter, EngineError
from .models import (
    ArtistProfile,
    Asset,
    CreditEntry,
    User,
    VoiceAdapter,
    VoiceAnalysis,
    VoiceDataset,
    VoiceDatasetVersion,
    VoiceProfile,
    VoiceRecording,
    Worker,
    WorkerCapability,
    new_uuid,
    utcnow,
)
from .orchestration import (
    append_event,
    cancel_attempt,
    claim_attempt,
    complete_attempt,
    fail_attempt,
    get_job_by_id,
    heartbeat,
    is_cancelling,
    set_job_stage,
)
from .queue import RedisQueue, build_redis
from .separator import NullSeparator, Separator, SeparatorUnavailable
from .storage import Storage, build_storage
from .training_acestep import AceStepTrainingAdapter
from .uais import embedding
from .uais.qc import decode_pcm16_mono
from .worker import validate_wav

log = logging.getLogger("oal.training_worker")

VALIDATION_PROMPT = "upbeat pop-rock, clear steady lead vocal"
VALIDATION_SEED = 777


class TrainingWorker:
    def __init__(
        self,
        db: Db,
        queue: RedisQueue,
        storage: Storage,
        settings: Settings,
        adapter: AceStepTrainingAdapter,
        gen_adapter: AceStepAdapter,
        separator: Separator | None = None,
        worker_id: str | None = None,
    ) -> None:
        self.db = db
        self.queue = queue
        self.storage = storage
        self.settings = settings
        self.adapter = adapter
        self.gen_adapter = gen_adapter
        self.separator: Separator = separator or NullSeparator()
        self.worker_id = worker_id or (
            f"{settings.worker_id}-training"
            if settings.worker_id
            else f"training-{socket.gethostname()}-{os.getpid()}"
        )
        self.queues = [RedisQueue.queue_name(settings.train_queue_model_id)]
        if settings.train_xl_queue_model_id != settings.train_queue_model_id:
            self.queues.append(RedisQueue.queue_name(settings.train_xl_queue_model_id))
        self.node_key = (settings.node_key or socket.gethostname())
        self._stop = False
        if settings.train_cuda_device and "CUDA_VISIBLE_DEVICES" not in os.environ:
            os.environ["CUDA_VISIBLE_DEVICES"] = settings.train_cuda_device

    # -- infrastructure --------------------------------------------------------

    def _gpu_available(self) -> bool:
        if self.settings.train_min_free_mb <= 0:
            return True
        import subprocess

        idx = self.settings.train_cuda_device or "0"
        try:
            out = subprocess.run(
                ["nvidia-smi", f"--id={idx}", "--query-gpu=memory.free",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=10,
            )
            free = int(out.stdout.strip().splitlines()[0])
        except Exception:
            return True
        return free >= self.settings.train_min_free_mb

    def _gpu_total_mb(self) -> int | None:
        import subprocess

        idx = self.settings.train_cuda_device or "0"
        try:
            out = subprocess.run(
                ["nvidia-smi", f"--id={idx}", "--query-gpu=memory.total",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=10,
            )
            return int(out.stdout.strip().splitlines()[0])
        except Exception:
            return None

    def _asset_bytes(self, asset) -> bytes:
        try:
            return self.storage.get(asset.storage_key).body
        except FileNotFoundError:
            if not self.settings.backend_url:
                raise
            import urllib.request

            url = (
                f"{self.settings.backend_url.rstrip('/')}/internal/v1/assets/{asset.id}/content"
                f"?x_oal_secret={self.settings.secret_key}"
            )
            with urllib.request.urlopen(url, timeout=self.settings.train_http_timeout_seconds) as resp:
                return resp.read()

    def register(self) -> None:
        from .fleet_nodes import register_node
        from .uais.capabilities import VOICE_CAPABILITIES

        with self.db.session() as session:
            register_node(session, self.node_key, worker_id=self.worker_id)
        total_mb = self._gpu_total_mb()
        with self.db.session() as session:
            worker = session.get(Worker, self.worker_id)
            if worker is None:
                session.add(Worker(id=self.worker_id, kind="training", vram_total_mb=total_mb))
            else:
                worker.last_heartbeat = utcnow()
                if total_mb is not None:
                    worker.vram_total_mb = total_mb
            for cap in VOICE_CAPABILITIES.values():
                if cap.training_recipe is None:
                    continue
                row = session.execute(
                    select(WorkerCapability).where(
                        WorkerCapability.worker_id == self.worker_id,
                        WorkerCapability.model_selection == cap.model_selection,
                        WorkerCapability.execution_profile_id == "voice.train",
                    )
                ).scalars().first()
                if row is None:
                    session.add(WorkerCapability(
                        id=new_uuid(), worker_id=self.worker_id,
                        model_selection=cap.model_selection,
                        execution_profile_id="voice.train",
                        engine_model=cap.engine_model,
                        tasks_json=["lora_train"],
                        vram_total_mb=total_mb,
                    ))
                else:
                    row.enabled = True
                    row.vram_total_mb = total_mb
                    row.updated_at = utcnow()
            session.commit()

    def _draining(self) -> bool:
        now = time.monotonic()
        if now - getattr(self, "_drain_checked_at", 0.0) < 5.0:
            return getattr(self, "_drain_flag", False)
        try:
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
        if not self._gpu_available():
            log.info("training GPU below free-VRAM gate; deferring to remote capacity")
            time.sleep(5)
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
            if operation == "voice.train":
                self._train(claimed_job, attempt_id, lease_token)
            elif operation == "voice.analyze":
                self._analyze(claimed_job, attempt_id, lease_token)
            elif operation == "voice.validate":
                self._validate(claimed_job, attempt_id, lease_token)
            elif operation == "model_lab.train":
                self._model_lab_train(claimed_job, attempt_id, lease_token)
            elif operation == "model_lab.merge":
                self._model_lab_merge(claimed_job, attempt_id, lease_token)
            else:
                fail_attempt(self.db, self.settings, claimed_job, attempt_id, lease_token,
                             "OPERATION_UNSUPPORTED", f"Training worker cannot run {operation!r}.")
        except EngineError as exc:
            fail_attempt(self.db, self.settings, claimed_job, attempt_id, lease_token, exc.code, exc.message)
        except Exception as exc:
            log.exception("training iteration failed")
            fail_attempt(self.db, self.settings, claimed_job, attempt_id, lease_token, "TRAINING_FAILED", str(exc)[:300])
        return True

    # -- credits -----------------------------------------------------------------

    def _refund(self, job_id: str, owner_id: str, charge_reason: str, amount: int) -> None:
        if amount <= 0 or not owner_id.startswith("usr_"):
            return
        with self.db.session() as session:
            charged = session.execute(
                select(CreditEntry).where(CreditEntry.external_id == f"voice-{charge_reason}:{job_id}")
            ).scalar_one_or_none()
            if charged is None:
                return
            existing = session.execute(
                select(CreditEntry).where(CreditEntry.external_id == f"voice-refund:{job_id}")
            ).scalar_one_or_none()
            if existing is not None:
                return
            user = session.get(User, owner_id[4:])
            if user is not None:
                user.credits_balance += amount
            session.add(CreditEntry(owner_id=owner_id, delta=amount, reason="training_refund",
                                    job_id=job_id, external_id=f"voice-refund:{job_id}"))
            session.commit()

    # -- engine --------------------------------------------------------------------

    def _ensure_engine_ready(self, on_wait=None) -> None:
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

    def _load_fresh(self, adapter_path: str) -> None:
        try:
            self.adapter.unload_lora()
        except EngineError:
            pass
        self.adapter.load_lora(adapter_path, adapter_name=f"oal-{uuid4().hex[:8]}")

    @staticmethod
    def _resolve_adapter_dir(export_path: str) -> str:
        root = Path(export_path)
        if (root / "adapter_config.json").is_file():
            return str(root)
        nested = root / "adapter"
        if (nested / "adapter_config.json").is_file():
            return str(nested)
        raise EngineError("ARTIFACT_INVALID", f"No PEFT adapter found under {export_path}.")

    def _materialize_adapter(self, adapter: VoiceAdapter) -> str:
        prefix, files = adapter.storage_prefix, list(adapter.files_json or [])
        if not prefix or not files:
            raise EngineError("ARTIFACT_MISSING", "Adapter has no durable artifact files.")
        cache = Path(self.settings.adapter_cache_dir) / adapter.id
        cache.mkdir(parents=True, exist_ok=True)
        for name in files:
            target = cache / name
            if not target.is_file():
                target.write_bytes(self.storage.get(f"{prefix}/{name}").body)
        return str(cache)

    # -- voice.train -----------------------------------------------------------------

    def _train(self, job_id: str, attempt_id: str, lease_token: str) -> None:
        stop_hb = threading.Event()

        def _keepalive() -> None:
            while not stop_hb.wait(10):
                heartbeat(self.db, attempt_id, lease_token)

        keepalive = threading.Thread(target=_keepalive, daemon=True)
        keepalive.start()
        try:
            self._train_inner(job_id, attempt_id, lease_token)
        except Exception:
            with self.db.session() as session:
                job = get_job_by_id(session, job_id)
                adapter_id = dict(job.request_json or {}).get("adapter_id")
                adapter = session.get(VoiceAdapter, adapter_id) if adapter_id else None
                if adapter is not None and adapter.state == "training":
                    adapter.state = "failed"
                    adapter.error_code = adapter.error_code or "TRAINING_FAILED"
                    session.commit()
            with self.db.session() as session:
                job = get_job_by_id(session, job_id)
                owner_id = job.owner_id
            self._refund(job_id, owner_id, "train", self.settings.credit_cost_training)
            raise
        finally:
            stop_hb.set()

    def _train_inner(self, job_id: str, attempt_id: str, lease_token: str) -> None:
        with self.db.session() as session:
            job = get_job_by_id(session, job_id)
            request = dict(job.request_json)
            owner_id = job.owner_id
            adapter = session.get(VoiceAdapter, request["adapter_id"])
            if adapter is None or adapter.owner_id != owner_id:
                fail_attempt(self.db, self.settings, job_id, attempt_id, lease_token,
                             "ADAPTER_NOT_FOUND", "Adapter record missing.")
                return
            adapter.state = "training"
            session.commit()
            version = session.get(VoiceDatasetVersion, adapter.dataset_version_id)
            artist = session.get(ArtistProfile, adapter.artist_profile_id)
            manifest = list((version.manifest_json or {}).get("recordings", [])) if version else []
            asset_ids = [m["asset_id"] for m in manifest]
            assets = {aid: session.get(Asset, aid) for aid in asset_ids}
            captions = {m["asset_id"]: m.get("caption") for m in manifest}
            artist_name = artist.name if artist else "artist"
            adapter_id = adapter.id
            training_config = dict(adapter.training_config_json or {})
        if not manifest:
            raise EngineError("DATASET_EMPTY", "Frozen dataset version has no recordings.")

        epochs = int(training_config.get("max_epochs") or 10)
        seed = int(training_config.get("seed") or 42)
        max_wall = self.settings.train_max_wall_seconds

        workdir = Path(self.settings.train_workdir).resolve() / job_id
        dataset_dir = workdir / "dataset"
        dataset_dir.mkdir(parents=True, exist_ok=True)
        for index, asset_id in enumerate(asset_ids):
            asset = assets.get(asset_id)
            if asset is None:
                raise EngineError("ASSET_MISSING", f"Recording asset {asset_id} missing.")
            (dataset_dir / f"track{index}.wav").write_bytes(self._asset_bytes(asset))
            caption = captions.get(asset_id) or f"{artist_name.lower()} vocal recording"
            (dataset_dir / f"track{index}.json").write_text(json.dumps({"caption": caption}), encoding="utf-8")

        set_job_stage(self.db, job_id, "preparing dataset")
        self._ensure_engine_ready()
        self.adapter.scan_dataset(str(dataset_dir), f"oal-{job_id[:8]}", True)
        self.adapter.preprocess(str(workdir / "tensors"))
        heartbeat(self.db, attempt_id, lease_token)
        self.adapter.start_training(
            str(workdir / "tensors"), str(workdir / "lora"), epochs=epochs, seed=seed,
            hyperparams={k: v for k, v in (training_config.get("hyperparams") or {}).items()},
        )

        deadline = time.monotonic() + max_wall
        poll = self.settings.train_poll_seconds
        status: dict = {}
        while True:
            if is_cancelling(self.db, job_id):
                self.adapter.stop_training()
                cancel_attempt(self.db, job_id, attempt_id, lease_token)
                with self.db.session() as session:
                    adapter = session.get(VoiceAdapter, adapter_id)
                    adapter.state = "failed"
                    adapter.error_code = "CANCELLED"
                    session.commit()
                self._refund(job_id, owner_id, "train", self.settings.credit_cost_training)
                return
            status = self.adapter.training_status()
            heartbeat(self.db, attempt_id, lease_token)
            done_epochs = int(status.get("current_epoch", 0) or 0)
            set_job_stage(self.db, job_id, "training", round(min(0.95, done_epochs / max(1, epochs)), 2))
            if not status.get("is_training", False):
                break
            if time.monotonic() > deadline:
                self.adapter.stop_training()
                with self.db.session() as session:
                    adapter = session.get(VoiceAdapter, adapter_id)
                    adapter.state = "failed"
                    adapter.error_code = "TRAINING_TIMEOUT"
                    session.commit()
                fail_attempt(self.db, self.settings, job_id, attempt_id, lease_token, "TRAINING_TIMEOUT",
                             "Training exceeded the wall-clock budget.")
                self._refund(job_id, owner_id, "train", self.settings.credit_cost_training)
                return
            time.sleep(poll)

        if status.get("error"):
            with self.db.session() as session:
                adapter = session.get(VoiceAdapter, adapter_id)
                adapter.state = "failed"
                adapter.error_code = "TRAINING_FAILED"
                adapter.error_message = str(status["error"])[:300]
                session.commit()
            raise EngineError("TRAINING_FAILED", str(status["error"])[:300])

        set_job_stage(self.db, job_id, "exporting adapter", 0.97)
        export = self.adapter.export(str(workdir / "lora"), str(workdir / "adapter"))
        adapter_path = self._resolve_adapter_dir(export.get("export_path", str(workdir / "adapter")))
        self._load_fresh(adapter_path)
        try:
            self.adapter.unload_lora()
        except EngineError:
            pass

        adapter_prefix = f"owners/{owner_id}/adapters/{adapter_id}"
        adapter_files = sorted(p.name for p in Path(adapter_path).iterdir() if p.is_file())
        if not adapter_files:
            raise EngineError("ARTIFACT_INVALID", "Exported adapter directory is empty.")
        digest = hashlib.sha256()
        for name in adapter_files:
            body = (Path(adapter_path) / name).read_bytes()
            self.storage.put(f"{adapter_prefix}/{name}", body)
            digest.update(name.encode())
            digest.update(body)

        history = status.get("loss_history") or []
        metrics = {
            "steps": status.get("current_step", 0),
            "epochs_completed": status.get("current_epoch", 0),
            "final_loss": history[-1]["loss"] if history else status.get("current_loss"),
            "steps_per_second": status.get("steps_per_second", 0.0),
            "adapter_loadable": True,
            "hardware": socket.gethostname(),
        }
        with self.db.session() as session:
            adapter = session.get(VoiceAdapter, adapter_id)
            adapter.state = "ready"
            adapter.storage_prefix = adapter_prefix
            adapter.files_json = adapter_files
            adapter.adapter_sha256 = digest.hexdigest()
            adapter.metrics_json = metrics
            adapter.error_code = None
            adapter.error_message = None
            job_row = get_job_by_id(session, job_id)
            job_row.status = "succeeded"
            job_row.stage = "done"
            job_row.progress = 1.0
            job_row.progress_source = "training"
            job_row.finished_at = utcnow()
            append_event(session, job_id, "succeeded", "succeeded", stage="done", progress=1.0, attempt_id=attempt_id)
            session.commit()

    # -- voice.analyze -----------------------------------------------------------------

    def _analyze(self, job_id: str, attempt_id: str, lease_token: str) -> None:
        with self.db.session() as session:
            job = get_job_by_id(session, job_id)
            request = dict(job.request_json)
            owner_id = job.owner_id
            artist_id = request["profile_id"]
            dataset = session.execute(
                select(VoiceDataset).where(VoiceDataset.artist_profile_id == artist_id)
            ).scalars().first()
            if dataset is None or dataset.latest_version_number == 0:
                fail_attempt(self.db, self.settings, job_id, attempt_id, lease_token,
                             "VOICE_NO_DATASET", "No frozen dataset version to analyze.")
                return
            version = session.execute(
                select(VoiceDatasetVersion).where(
                    VoiceDatasetVersion.dataset_id == dataset.id,
                    VoiceDatasetVersion.version_number == dataset.latest_version_number,
                )
            ).scalars().first()
            manifest = list((version.manifest_json or {}).get("recordings", []))
            assets = {m["recording_id"]: session.get(Asset, m["asset_id"]) for m in manifest}

        embeddings: dict[str, list[float]] = {}
        input_types: dict[str, str] = {}
        vocal_stems: dict[str, dict] = {}
        separator_note: str | None = None
        for recording_id, asset in assets.items():
            if asset is None:
                continue
            heartbeat(self.db, attempt_id, lease_token)
            body = self._asset_bytes(asset)
            stem_body: bytes | None = None
            if separator_note is None:
                try:
                    stem_body = self.separator.separate(body)["vocals"]
                except SeparatorUnavailable as exc:
                    separator_note = str(exc)
            source = stem_body if stem_body is not None else body
            with tempfile.TemporaryDirectory(prefix="oal-an-") as tmp:
                path = Path(tmp) / "audio"
                path.write_bytes(source)
                samples = decode_pcm16_mono(self.settings.ffmpeg_bin, path,
                                            self.settings.voice_max_recording_seconds)
            embeddings[recording_id] = embedding.embed_pcm16(samples)
            input_types[recording_id] = "vocal_stem" if stem_body is not None else "full_mix"
            if stem_body is not None:
                key = f"owners/{owner_id}/voice/{dataset.id}/{recording_id}-vocals.wav"
                sha256 = self.storage.put(key, stem_body)
                vocal_stems[recording_id] = {"key": key, "sha256": sha256, "bytes": len(stem_body)}
        if not embeddings:
            raise EngineError("VOICE_NO_AUDIO", "No analyzable recordings in the dataset version.")
        types = set(input_types.values())
        input_type = types.pop() if len(types) == 1 else "mixed"
        vectors = list(embeddings.values())
        centroid = embedding.centroid(vectors)
        pairwise = [embedding.cosine(a, b) for i, a in enumerate(vectors) for b in vectors[i + 1:]]
        mean_pairwise = round(sum(pairwise) / len(pairwise), 4) if pairwise else None
        min_pairwise = round(min(pairwise), 4) if pairwise else None
        # Phase F: genre-independence is *estimated* from cross-recording
        # embedding consistency (different songs, ideally different genres);
        # it is not a measured genre-transform and not a quality score.
        basis = ("cross-recording embedding consistency on separated vocal stems"
                 if input_type == "vocal_stem"
                 else "cross-recording embedding consistency on full mixes")
        identity = {
            "embedding_model": self.settings.voice_embedding_model,
            "input_type": input_type,
            "recordings": len(embeddings),
            "mean_pairwise_similarity": mean_pairwise,
            "min_pairwise_similarity": min_pairwise,
            "genre_independence": {
                "estimate": mean_pairwise,
                "basis": basis + " (proxy, not a measured genre transform)",
                "separator": self.separator.name if input_type == "vocal_stem" else
                             f"unavailable ({separator_note})" if separator_note else "none",
            },
        }

        with self.db.session() as session:
            latest = session.execute(
                select(VoiceProfile)
                .where(VoiceProfile.artist_profile_id == artist_id)
                .order_by(VoiceProfile.version_number.desc())
            ).scalars().first()
            if latest is None or latest.dataset_version_id != version.id:
                profile = VoiceProfile(
                    id=new_uuid(), artist_profile_id=artist_id, owner_id=owner_id,
                    version_number=(latest.version_number + 1) if latest else 1,
                    dataset_version_id=version.id,
                    description_json=dict(latest.description_json) if latest else {},
                    performance_json=dict(latest.performance_json) if latest else {},
                    is_default=latest is None,
                )
                session.add(profile)
            else:
                profile = latest
            profile.embeddings_json = {
                "model": self.settings.voice_embedding_model,
                "input_type": input_type,
                "recordings": embeddings,
                "centroid": centroid,
            }
            profile.identity_json = identity
            profile.analysis_model = self.settings.voice_embedding_model
            profile.status = "analyzed"
            for recording_id, stem in vocal_stems.items():
                recording = session.get(VoiceRecording, recording_id)
                if recording is None:
                    continue
                stem_asset = Asset(
                    id=new_uuid(), job_id=job_id, owner_id=owner_id, storage_key=stem["key"],
                    role="training_stem", kind="derived", mime="audio/wav",
                    bytes=stem["bytes"], sha256=stem["sha256"],
                    title=f"{recording.filename} (vocal stem)", finalized_at=utcnow(),
                )
                session.add(stem_asset)
                session.flush()
                recording.vocal_asset_id = stem_asset.id
                recording.separation_json = {"separator": self.separator.name,
                                             "separated_at": utcnow().isoformat()}
            session.add(VoiceAnalysis(
                id=new_uuid(), artist_profile_id=artist_id, owner_id=owner_id,
                dataset_version_id=version.id, job_id=job_id,
                embedding_model=self.settings.voice_embedding_model,
                input_type=input_type,
                result_json={"recordings": len(embeddings), "dim": embedding.DIM,
                             "mean_pairwise_similarity": mean_pairwise,
                             "min_pairwise_similarity": min_pairwise,
                             "separator": identity["genre_independence"]["separator"]},
            ))
            artist = session.get(ArtistProfile, artist_id)
            if artist is not None and artist.default_voice_profile_id is None:
                artist.default_voice_profile_id = profile.id
            job_row = get_job_by_id(session, job_id)
            job_row.status = "succeeded"
            job_row.stage = "done"
            job_row.progress = 1.0
            job_row.progress_source = "analysis"
            job_row.finished_at = utcnow()
            append_event(session, job_id, "succeeded", "succeeded", stage="done", progress=1.0, attempt_id=attempt_id)
            session.commit()

    # -- model_lab.train / model_lab.merge -------------------------------------------

    def _supervised_run(self, command: str, env: dict, job_id: str,
                        attempt_id: str, lease_token: str, wall_hours: float):
        """Run a long trainer/merge command with continuous lease renewal,
        cancellation and hard wall deadline. Returns (returncode, stdout, stderr,
        outcome) where outcome is ok|cancelled|timeout|lease-lost."""
        import tempfile

        out = tempfile.NamedTemporaryFile("w+", suffix=".out", delete=False)
        err = tempfile.NamedTemporaryFile("w+", suffix=".err", delete=False)
        proc = subprocess.Popen(command, shell=True, stdout=out, stderr=err,
                                env=env, text=True, start_new_session=True)
        deadline = time.monotonic() + max(0.1, wall_hours) * 3600.0
        outcome = "ok"
        while proc.poll() is None:
            time.sleep(10.0)
            if not heartbeat(self.db, attempt_id, lease_token):
                outcome = "lease-lost"
                self._kill_group(proc, signal.SIGKILL)
                break
            if is_cancelling(self.db, job_id):
                outcome = "cancelled"
                self._kill_group(proc, signal.SIGTERM)
                break
            if time.monotonic() > deadline:
                outcome = "timeout"
                self._kill_group(proc, signal.SIGKILL)
                break
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            self._kill_group(proc, signal.SIGKILL)
            proc.wait(timeout=30)
        out.close(); err.close()
        stdout = Path(out.name).read_text(errors="replace")
        stderr = Path(err.name).read_text(errors="replace")
        for f in (out.name, err.name):
            try:
                os.unlink(f)
            except OSError:
                pass
        return proc.returncode, stdout, stderr, outcome

    @staticmethod
    def _kill_group(proc, sig) -> None:
        try:
            os.killpg(os.getpgid(proc.pid), sig)
        except (ProcessLookupError, PermissionError):
            pass

    @staticmethod
    def _last_json(stdout: str) -> dict:
        for line in reversed((stdout or "").splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    pass
        return {}

    def _model_lab_train(self, job_id: str, attempt_id: str, lease_token: str) -> None:
        from .model_lab_train import settle_attempt
        from .models import MlBudget, MlTrainingAttempt

        command = (self.settings.model_lab_train_command or "").strip()
        if not command:
            with self.db.session() as session:
                job = get_job_by_id(session, job_id)
                request = dict(job.request_json)
                attempt = session.get(MlTrainingAttempt, request.get("attempt_id"))
                if attempt is not None:
                    settle_attempt(session, attempt, state="failed",
                                   error="TRAINER_UNAVAILABLE",
                                   budget=session.get(MlBudget, attempt.budget_id))
            fail_attempt(self.db, self.settings, job_id, attempt_id, lease_token,
                         "TRAINER_UNAVAILABLE",
                         "model_lab.train needs OAL_MODEL_LAB_TRAIN_COMMAND.")
            return
        with self.db.session() as session:
            job = get_job_by_id(session, job_id)
            request = dict(job.request_json)
            attempt = session.get(MlTrainingAttempt, request.get("attempt_id"))
            if attempt is not None:
                attempt.state = "running"  # running only after claim
                attempt.worker_id = self.worker_id
                session.commit()
        from .fleet_nodes import claim_for_training
        with self.db.session() as session:
            reserved = claim_for_training(session, self.node_key, request.get("attempt_id", ""))
        if not reserved:
            # A node record exists but is not exclusively reserved for us:
            # another claim won the race or the node is not in training pool.
            from .fleet_nodes import NODE_STATES  # noqa: F401
            with self.db.session() as session:
                job2 = get_job_by_id(session, job_id)
                req2 = dict(job2.request_json)
                attempt = session.get(MlTrainingAttempt, req2.get("attempt_id"))
                if attempt is not None:
                    settle_attempt(session, attempt, state="failed",
                                   error="NODE_NOT_RESERVED",
                                   budget=session.get(MlBudget, attempt.budget_id))
            fail_attempt(self.db, self.settings, job_id, attempt_id, lease_token,
                         "NODE_NOT_RESERVED",
                         f"node {self.node_key} is not in training_reserved state.")
            return
        env = dict(os.environ)
        env["OAL_ML_ATTEMPT_ID"] = request.get("attempt_id", "")
        env["OAL_ML_DATASET_SHA"] = request.get("frozen_sha256", "")
        rc, stdout, stderr, outcome = self._supervised_run(
            command, env, job_id, attempt_id, lease_token,
            self.settings.model_lab_run_wall_hours)
        result = self._last_json(stdout)
        code = {"ok": None, "cancelled": "TRAINING_CANCELLED",
                "timeout": "TRAINING_TIMEOUT",
                "lease-lost": "LEASE_LOST"}[outcome]
        ok = outcome == "ok" and rc == 0
        if ok and not (result.get("artifact_key") and result.get("sha256")):
            ok, code = False, "TRAINING_NO_ARTIFACT"  # a successful no-op fails
        with self.db.session() as session:
            attempt = session.get(MlTrainingAttempt, request.get("attempt_id"))
            if attempt is not None:
                budget = session.get(MlBudget, attempt.budget_id)
                settle_attempt(session, attempt,
                               state="done" if ok else "failed",
                               hours=result.get("hours"), spend_usd=result.get("spend_usd"),
                               error=None if ok else (code + ": " + (stderr or "")[-200:]),
                               budget=budget)
        self._release_node()
        if not ok:
            fail_attempt(self.db, self.settings, job_id, attempt_id, lease_token,
                         code or "TRAINING_FAILED", (stderr or code or "trainer failed")[-280:])
            return
        complete_attempt(self.db, self.storage, self.settings, job_id, attempt_id,
                         lease_token, ("train-result", json.dumps(result).encode()),
                         synthetic=False,
                         engine_result={"trainer": command.split()[0], "result": result})

    def _release_node(self) -> None:
        """active -> cleanup -> shared_ready (no-op when not under contract)."""
        from .fleet_nodes import cleanup_done, finish_training

        with self.db.session() as session:
            finish_training(session, self.node_key)
            cleanup_done(session, self.node_key)

    def _model_lab_merge(self, job_id: str, attempt_id: str, lease_token: str) -> None:
        from .model_lab_merge import finish_merge_build
        from .models import MlModelBundle

        command = (self.settings.model_lab_merge_command or "").strip()
        if not command:
            fail_attempt(self.db, self.settings, job_id, attempt_id, lease_token,
                         "MERGE_UNAVAILABLE", "model_lab.merge needs OAL_MODEL_LAB_MERGE_COMMAND.")
            return
        with self.db.session() as session:
            job = get_job_by_id(session, job_id)
            request = dict(job.request_json)
            bundle = session.get(MlModelBundle, request.get("bundle_id"))
            bundle_id = bundle.id if bundle is not None else None
        if bundle_id is None:
            fail_attempt(self.db, self.settings, job_id, attempt_id, lease_token,
                         "BUNDLE_NOT_FOUND", "Merge build bundle record missing.")
            return
        env = dict(os.environ)
        env["OAL_ML_BUNDLE_ID"] = bundle_id
        env["OAL_ML_RECIPE_ID"] = request.get("recipe_id", "")
        env["OAL_ML_BASE_MODEL"] = request.get("base_model", "")
        env["OAL_ML_ADAPTERS"] = ",".join(request.get("adapter_ids") or [])
        env["OAL_ML_METHOD"] = request.get("method", "slerp")
        rc, stdout, stderr, outcome = self._supervised_run(
            command, env, job_id, attempt_id, lease_token,
            self.settings.model_lab_merge_wall_hours)
        result = self._last_json(stdout)
        ok = outcome == "ok" and rc == 0 and result.get("sha256")
        with self.db.session() as session:
            bundle = session.get(MlModelBundle, bundle_id)
            finish_merge_build(session, bundle, ok=ok, result=result,
                               error=None if ok else f"{outcome or 'merge'} rc={rc}")
        if not ok:
            fail_attempt(self.db, self.settings, job_id, attempt_id, lease_token,
                         "MERGE_FAILED", (stderr or outcome or "merge failed")[-280:])
            return
        complete_attempt(self.db, self.storage, self.settings, job_id, attempt_id,
                         lease_token, ("merge-result", json.dumps(result).encode()),
                         synthetic=False, engine_result=result)

    # -- voice.validate ------------------------------------------------------------------

    def _validate(self, job_id: str, attempt_id: str, lease_token: str) -> None:
        with self.db.session() as session:
            job = get_job_by_id(session, job_id)
            request = dict(job.request_json)
            owner_id = job.owner_id
            adapter = session.get(VoiceAdapter, request["adapter_id"])
            if adapter is None or adapter.owner_id != owner_id:
                fail_attempt(self.db, self.settings, job_id, attempt_id, lease_token,
                             "ADAPTER_NOT_FOUND", "Adapter record missing.")
                return
            adapter_id = adapter.id
            profile = session.get(VoiceProfile, adapter.voice_profile_id) if adapter.voice_profile_id else None
            centroid = ((profile.embeddings_json or {}).get("centroid") if profile else None)
        if not centroid:
            self._refund(job_id, owner_id, "validate", self.settings.credit_cost_validation)
            raise EngineError("VOICE_NOT_ANALYZED",
                              "Run voice analysis before validation; no reference centroid exists.")

        try:
            self._validate_inner(job_id, attempt_id, lease_token, adapter_id, centroid)
        except Exception:
            self._refund(job_id, owner_id, "validate", self.settings.credit_cost_validation)
            raise

    def _validate_inner(self, job_id: str, attempt_id: str, lease_token: str,
                        adapter_id: str, centroid: list[float]) -> None:
        with self.db.session() as session:
            adapter = session.get(VoiceAdapter, adapter_id)
            path = self._materialize_adapter(adapter)
        self._load_fresh(path)
        heartbeat(self.db, attempt_id, lease_token)
        try:
            self.adapter.set_use_lora(True)
            sample = self._generate_sample()
            heartbeat(self.db, attempt_id, lease_token)
            try:
                stems = self.separator.separate(sample["body"])
            except SeparatorUnavailable as exc:
                raise EngineError("SEPARATOR_UNAVAILABLE", str(exc)) from exc
            with tempfile.TemporaryDirectory(prefix="oal-va-") as tmp:
                vocal_path = Path(tmp) / "vocals.wav"
                vocal_path.write_bytes(stems["vocals"])
                samples = decode_pcm16_mono(self.settings.ffmpeg_bin, vocal_path,
                                            self.settings.voice_max_recording_seconds)
        finally:
            self.adapter.set_use_lora(False)
            try:
                self.adapter.unload_lora()
            except EngineError:
                pass

        vocal_embedding = embedding.embed_pcm16(samples)
        similarity = embedding.cosine(vocal_embedding, centroid)
        threshold = self.settings.voice_similarity_threshold
        passed = similarity >= threshold
        validation = {
            "similarity": round(similarity, 4),
            "threshold": threshold,
            "passed": passed,
            "embedding_model": self.settings.voice_embedding_model,
            "separator": self.separator.name,
            "sample": {k: v for k, v in sample.items() if k != "body"},
            "note": "Calibration threshold, not a scientifically established voice-accuracy percentage.",
        }
        with self.db.session() as session:
            adapter = session.get(VoiceAdapter, adapter_id)
            adapter.validation_json = validation
            adapter.last_validated_at = utcnow()
            if passed:
                adapter.state = "validated"
            job_row = get_job_by_id(session, job_id)
            job_row.status = "succeeded"
            job_row.stage = "done"
            job_row.progress = 1.0
            job_row.progress_source = "validation"
            job_row.finished_at = utcnow()
            append_event(session, job_id, "succeeded", "succeeded", stage="done", progress=1.0, attempt_id=attempt_id)
            session.commit()

    def _generate_sample(self) -> dict:
        payload = self.gen_adapter.build_payload(
            music_description=VALIDATION_PROMPT, lyrics=None, instrumental=False,
            seed=VALIDATION_SEED, duration_seconds=12,
        )
        submit = self.gen_adapter.submit(payload)
        deadline = time.monotonic() + self.settings.engine_timeout_seconds
        while True:
            state, result = self.gen_adapter.poll(submit.task_id)
            if state == "succeeded":
                break
            if state == "failed":
                raise EngineError("ENGINE_GENERATION_FAILED", "Validation generation failed.")
            if time.monotonic() > deadline:
                raise EngineError("ENGINE_TIMEOUT", "Validation generation timed out.")
            time.sleep(self.settings.engine_poll_seconds)
        file_url = (result or [{}])[0].get("file")
        if not file_url:
            raise EngineError("ENGINE_NO_AUDIO", "Validation generation returned no audio.")
        body = self.gen_adapter.download(file_url)
        rate, channels, duration = validate_wav(body, self.settings.max_artifact_bytes)
        return {"body": body, "sample_rate": rate, "channels": channels,
                "duration_seconds": round(duration, 3), "bytes": len(body)}

    # -- loop --------------------------------------------------------------------------

    def run_forever(self) -> None:
        from .fleet_nodes import heartbeat_node, supervisor_tick

        self.register()
        while not self._stop:
            try:
                self.run_once()
                with self.db.session() as session:
                    heartbeat_node(session, self.node_key)
                    stale = supervisor_tick(session, self.settings.node_stale_seconds)
                for node_id in stale:
                    log.warning("supervisor quarantined node %s (stale heartbeat)", node_id)
            except Exception:
                log.exception("training worker iteration failed")
                time.sleep(2)

    def stop(self) -> None:
        self._stop = True


def build_training_worker() -> TrainingWorker:
    from .engine_acestep import RequestsTransport
    from .separator import DemucsSeparator

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
    separator = (
        DemucsSeparator(settings.demucs_python, settings.demucs_model, settings.demucs_device,
                        settings.separator_timeout_seconds)
        if settings.demucs_python else NullSeparator()
    )
    return TrainingWorker(
        db, queue, storage, settings,
        adapter=AceStepTrainingAdapter(transport),
        gen_adapter=AceStepAdapter(gen_transport, model=settings.acestep_model, thinking=settings.acestep_thinking),
        separator=separator,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    worker = build_training_worker()
    print(f"training worker {worker.worker_id} consuming {worker.queues}")
    try:
        worker.run_forever()
    except KeyboardInterrupt:
        worker.stop()
