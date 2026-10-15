"""Deterministic WAV fixture worker (opt-in; never real music).

Produces clearly labeled ``synthetic_test_audio`` so the full pipeline can run
without GPUs. Artifacts from this worker must never be presented as genuine
engine output.
"""

from __future__ import annotations

import hashlib
import io
import logging
import math
import os
import socket
import struct
import threading
import time
import wave
from datetime import datetime

from .config import Settings, get_settings
from .db import Db
from .models import Job, Worker, utcnow
from .orchestration import (
    append_event,
    cancel_attempt,
    claim_attempt,
    complete_attempt,
    fail_attempt,
    get_job_by_id,
    heartbeat,
    is_cancelling,
)
from .queue import RedisQueue, build_redis
from .storage import LocalObjectStorage

SAMPLE_RATE = 44100
FIXTURE_MAX_SECONDS = 10.0


class InvalidArtifact(Exception):
    pass


def generate_fixture_wav(lyrics_sha256: str | None, seed: int | None, duration_seconds: int | None) -> bytes:
    source = f"{lyrics_sha256 or 'instrumental'}:{seed if seed is not None else 'none'}"
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    frequency = 220.0 + (int(digest[:8], 16) % 220)
    seconds = min(float(duration_seconds or 5), FIXTURE_MAX_SECONDS)
    frames = int(SAMPLE_RATE * seconds)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        for index in range(frames):
            t = index / SAMPLE_RATE
            fade = min(1.0, t / 0.01, (seconds - t) / 0.05) if seconds > t else 0.0
            value = int(12000 * fade * math.sin(2 * math.pi * frequency * t))
            wav.writeframes(struct.pack("<h", value))
    return buffer.getvalue()


def validate_wav(body: bytes, max_bytes: int) -> tuple[int, int, float]:
    """Return (sample_rate, channels, duration). Raise InvalidArtifact otherwise."""
    if not body or len(body) > max_bytes:
        raise InvalidArtifact("Artifact exceeds the configured size limit or is empty.")
    try:
        with wave.open(io.BytesIO(body), "rb") as wav:
            channels = wav.getnchannels()
            rate = wav.getframerate()
            duration = wav.getnframes() / float(rate) if rate else 0.0
            if wav.getnframes() == 0 or wav.getsampwidth() == 0:
                raise InvalidArtifact("Artifact has no audio frames.")
    except (wave.Error, EOFError) as exc:
        raise InvalidArtifact("Artifact is not a decodable WAV file.") from exc
    return rate, channels, duration


class FixtureWorker:
    def __init__(
        self,
        db: Db,
        queue: RedisQueue,
        storage: LocalObjectStorage,
        settings: Settings,
        worker_id: str | None = None,
        queue_name: str | None = None,
    ) -> None:
        self.db = db
        self.queue = queue
        self.storage = storage
        self.settings = settings
        self.worker_id = worker_id or f"fixture-{socket.gethostname()}-{os.getpid()}"
        self.queue_name = queue_name or RedisQueue.queue_name("ace-step-1.5")
        self._stop = threading.Event()

    def register(self) -> None:
        with self.db.session() as session:
            worker = session.get(Worker, self.worker_id)
            if worker is None:
                session.add(Worker(id=self.worker_id, kind="fixture"))
            else:
                worker.last_heartbeat = utcnow()
            session.commit()

    def _heartbeat_thread(self, attempt_id: str, lease_token: str) -> tuple[threading.Thread, threading.Event]:
        stop = threading.Event()

        def loop() -> None:
            while not stop.wait(self.settings.heartbeat_interval_seconds):
                if not heartbeat(self.db, attempt_id, lease_token):
                    return

        thread = threading.Thread(target=loop, daemon=True)
        thread.start()
        return thread, stop

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
            payload = dict(job.request_json) if job else {}
            lyrics_sha = job.lyrics_sha256 if job else None
            append_event(session, claimed_job, "stage", "running", stage="generating", attempt_id=attempt_id)
            session.commit()
        thread, stop = self._heartbeat_thread(attempt_id, lease_token)
        try:
            time.sleep(self.settings.fixture_latency_seconds)
            if is_cancelling(self.db, claimed_job):
                cancel_attempt(self.db, claimed_job, attempt_id, lease_token)
                return True
            body = generate_fixture_wav(lyrics_sha, payload.get("seed"), payload.get("duration_seconds"))
        finally:
            stop.set()
            thread.join(timeout=1)
        try:
            rate, channels, duration = validate_wav(body, self.settings.max_artifact_bytes)
        except InvalidArtifact as exc:
            fail_attempt(self.db, self.settings, claimed_job, attempt_id, lease_token, "ARTIFACT_INVALID", str(exc))
            return True
        complete_attempt(
            self.db,
            self.storage,
            self.settings,
            claimed_job,
            attempt_id,
            lease_token,
            ("mix_wav", body),
            audio_meta=(rate, channels, duration),
        )
        return True

    def run_forever(self) -> None:
        self.register()
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:
                logging.getLogger("oal.worker").exception("fixture worker iteration failed")
                time.sleep(1)

    def stop(self) -> None:
        self._stop.set()


def build_worker() -> FixtureWorker:
    settings = get_settings()
    db = Db(settings.database_url)
    queue = RedisQueue(build_redis(settings.redis_url))
    storage = LocalObjectStorage(settings.storage_dir)
    return FixtureWorker(db, queue, storage, settings)


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO)
    worker = build_worker()
    print(f"fixture worker {worker.worker_id} consuming {worker.queue_name}")
    try:
        worker.run_forever()
    except KeyboardInterrupt:
        worker.stop()
