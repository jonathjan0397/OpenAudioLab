"""CPU audio worker: export jobs (mix WAV/MP3, separated stems, stem ZIP).

Separate queue and worker capability from GPU generation. Every requested
output must be published and validated before the job succeeds; on failure,
usable assets are preserved as partial results without overall success.
"""

from __future__ import annotations

import hashlib
import logging
import os
import socket
import time
from dataclasses import dataclass
from datetime import timedelta

from .audio_processing import (
    AudioProbe,
    AudioToolError,
    build_stems_zip,
    encode_mp3,
    encode_wav,
    probe_audio,
    probe_wav,
    tool_version,
)
from .config import Settings, get_settings
from .db import Db
from .models import Asset, ProjectVersion, Worker, new_uuid, utcnow
from .orchestration import (
    _finish_attempt,
    append_event,
    claim_attempt,
    fail_attempt,
    get_job_by_id,
    heartbeat,
    is_cancelling,
)
from .queue import RedisQueue, build_redis
from .separator import DemucsSeparator, NullSeparator, Separator, SeparatorUnavailable
from .storage import Storage, build_storage

log = logging.getLogger("oal.audio_worker")

EXPORT_MODEL_ID = "audio-export"
EXPORT_RECIPE_REVISION = "audio-export@1"
MP3_BITRATES = (128, 192, 256, 320)
OUTPUT_ORDER = ("mix_wav", "mix_mp3", "stems_wav", "stems_zip")


@dataclass
class ExportOutput:
    role: str
    body: bytes
    mime: str
    processing: str | None = None
    stem_source: str | None = None
    stem_category: str | None = None
    sample_rate: int | None = None
    channels: int | None = None
    duration_seconds: float | None = None


def _extension(role: str, mime: str) -> str:
    if role == "stems_zip":
        return "zip"
    if mime == "audio/mpeg":
        return "mp3"
    return "wav"


def finalize_export(
    db: Db,
    storage: Storage,
    settings: Settings,
    job_id: str,
    attempt_id: str,
    lease_token: str,
    outputs: list[ExportOutput],
    source_asset_id: str | None = None,
    error: tuple[str, str] | None = None,
) -> str:
    """Publish validated outputs; ``error`` keeps them as partial results."""
    with db.session() as session:
        if not _finish_attempt(session, attempt_id, lease_token, "succeeded" if error is None else "failed"):
            append_event(session, job_id, "discarded", "stale-lease", message="Lease lost before export.", attempt_id=attempt_id)
            session.commit()
            return "stale"
        job = get_job_by_id(session, job_id)
        if job is None or job.status != "running":
            if job is not None and job.status == "cancelling":
                job.status = "cancelled"
                job.finished_at = utcnow()
            append_event(session, job_id, "discarded", job.status if job else "unknown", message="Late export discarded.", attempt_id=attempt_id)
            session.commit()
            return "discarded"
        expires_at = utcnow() + timedelta(days=settings.asset_retention_days)
        for output in outputs:
            key = f"owners/{job.owner_id}/jobs/{job.id}/{attempt_id}/{output.role}.{_extension(output.role, output.mime)}"
            checksum = storage.put(key, output.body)
            session.add(
                Asset(
                    id=new_uuid(),
                    job_id=job.id,
                    owner_id=job.owner_id,
                    attempt_id=attempt_id,
                    storage_key=key,
                    role=output.role,
                    kind="exported",
                    source_asset_id=source_asset_id,
                    stem_source=output.stem_source,
                    stem_category=output.stem_category,
                    processing=output.processing,
                    mime=output.mime,
                    bytes=len(output.body),
                    sha256=checksum,
                    sample_rate=output.sample_rate,
                    channels=output.channels,
                    duration_seconds=round(output.duration_seconds, 3) if output.duration_seconds else None,
                    synthetic=False,
                    finalized_at=utcnow(),
                    expires_at=expires_at,
                )
            )
        if error is None:
            job.status = "succeeded"
            job.stage = "done"
            job.progress = 1.0
            job.progress_source = "export"
            append_event(session, job.id, "succeeded", "succeeded", stage="done", progress=1.0, attempt_id=attempt_id)
        else:
            code, message = error
            job.status = "failed"
            job.error_code = code
            job.error_message = message
            append_event(session, job.id, "failed", "failed", message=code, attempt_id=attempt_id)
        job.finished_at = utcnow()
        job.assets_expired_at = expires_at
        session.commit()
        return job.status


class AudioWorker:
    def __init__(
        self,
        db: Db,
        queue: RedisQueue,
        storage: Storage,
        settings: Settings,
        separator: Separator | None = None,
        worker_id: str | None = None,
    ) -> None:
        self.db = db
        self.queue = queue
        self.storage = storage
        self.settings = settings
        self.separator: Separator = separator or NullSeparator()
        self.worker_id = worker_id or (
            f"{settings.worker_id}-audio"
            if settings.worker_id
            else f"audio-{socket.gethostname()}-{os.getpid()}"
        )
        self.queue_name = RedisQueue.queue_name(EXPORT_MODEL_ID)
        self._stop = False

    def register(self) -> None:
        with self.db.session() as session:
            worker = session.get(Worker, self.worker_id)
            if worker is None:
                session.add(Worker(id=self.worker_id, kind="audio"))
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
        job_id = self.queue.receive(self.queue_name, self.settings.worker_brpop_timeout_seconds)
        if job_id is None:
            self.register()
            return False
        claim = claim_attempt(self.db, job_id, self.worker_id)
        if claim is None:
            return True
        claimed_job, attempt_id, lease_token = claim
        try:
            self._process(claimed_job, attempt_id, lease_token)
        except Exception as exc:  # worker boundary: never die on one job
            log.exception("export attempt failed unexpectedly")
            fail_attempt(
                self.db, self.settings, claimed_job, attempt_id, lease_token,
                "EXPORT_FAILED", str(exc)[:300],
            )
        return True

    def _process(self, job_id: str, attempt_id: str, lease_token: str) -> None:
        with self.db.session() as session:
            job = get_job_by_id(session, job_id)
            request = dict(job.request_json)
            version = session.get(ProjectVersion, request.get("source_version_id", ""))
            source_asset = (
                session.get(Asset, version.source_asset_id)
                if version is not None and version.source_asset_id
                else None
            )
            owner_ok = (
                version is not None
                and version.owner_id == job.owner_id
                and source_asset is not None
                and source_asset.owner_id == job.owner_id
                and source_asset.deleted_at is None
            )
            source_key = source_asset.storage_key if source_asset else None
            source_asset_id = source_asset.id if source_asset else None
        if not owner_ok or source_key is None:
            fail_attempt(self.db, self.settings, job_id, attempt_id, lease_token, "SOURCE_UNAVAILABLE", "Source version or asset is missing.")
            return

        source_body = self.storage.get(source_key).body
        outputs_wanted: list[str] = request.get("outputs", [])
        mp3_bitrate = int((request.get("mp3") or {}).get("bitrate_kbps", 320))

        wav_body = source_body
        wav_probe = probe_wav(source_body)
        if wav_probe is None:
            wav_body = encode_wav(self.settings.ffmpeg_bin, source_body)
            wav_probe = probe_wav(wav_body)
        if wav_probe is None:
            fail_attempt(self.db, self.settings, job_id, attempt_id, lease_token, "ARTIFACT_INVALID", "Source is not decodable audio.")
            return

        stems: dict[str, bytes] | None = None
        failure: tuple[str, str] | None = None
        if {"stems_wav", "stems_zip"} & set(outputs_wanted):
            try:
                stems = self.separator.separate(source_body)
                self._validate_alignment(stems)
            except SeparatorUnavailable as exc:
                failure = ("SEPARATOR_UNAVAILABLE", str(exc))
            except Exception as exc:
                failure = ("SEPARATOR_FAILED", str(exc)[:300])
        heartbeat(self.db, attempt_id, lease_token)

        results: list[ExportOutput] = []
        for output in [o for o in OUTPUT_ORDER if o in outputs_wanted]:
            if is_cancelling(self.db, job_id):
                from .orchestration import cancel_attempt

                cancel_attempt(self.db, job_id, attempt_id, lease_token)
                return
            try:
                results.extend(self._build_output(output, request, job_id, attempt_id, wav_body, wav_probe, mp3_bitrate, stems))
            except (AudioToolError, RuntimeError) as exc:
                failure = failure or ("EXPORT_FAILED", str(exc)[:300])
                break
            heartbeat(self.db, attempt_id, lease_token)

        with self.db.session() as session:
            from .models import JobAttempt

            attempt = session.get(JobAttempt, attempt_id)
            if attempt is not None:
                attempt.engine_version = f"ffmpeg-{tool_version_safe(self.settings.ffmpeg_bin)}+{self.separator.name}"
            session.commit()

        finalize_export(
            self.db,
            self.storage,
            self.settings,
            job_id,
            attempt_id,
            lease_token,
            results,
            source_asset_id=source_asset_id,
            error=failure,
        )

    @staticmethod
    def _validate_alignment(stems: dict[str, bytes]) -> None:
        probes = {category: probe_wav(body) for category, body in stems.items()}
        if any(probe is None for probe in probes.values()):
            raise RuntimeError("A separated stem is not valid WAV.")
        signatures = {
            (probe.sample_rate, probe.channels, probe.sample_count)
            for probe in probes.values()
            if probe is not None
        }
        if len(signatures) != 1:
            raise RuntimeError("Separated stems are not sample-aligned.")

    def _build_output(
        self,
        output: str,
        request: dict,
        job_id: str,
        attempt_id: str,
        wav_body: bytes,
        wav_probe: AudioProbe,
        mp3_bitrate: int,
        stems: dict[str, bytes] | None,
    ) -> list[ExportOutput]:
        if output == "mix_wav":
            return [
                ExportOutput(
                    role="mix_wav",
                    body=wav_body,
                    mime="audio/wav",
                    processing="native_copy",
                    sample_rate=wav_probe.sample_rate,
                    channels=wav_probe.channels,
                    duration_seconds=wav_probe.duration_seconds,
                )
            ]
        if output == "mix_mp3":
            mp3 = encode_mp3(self.settings.ffmpeg_bin, wav_body, mp3_bitrate)
            probe = probe_audio(mp3, self.settings.ffprobe_bin)
            if probe.codec != "mp3":
                raise RuntimeError("MP3 output failed codec validation.")
            if probe.bit_rate and abs(probe.bit_rate - mp3_bitrate * 1000) > 0.2 * mp3_bitrate * 1000:
                raise RuntimeError("MP3 output bitrate is far from the requested setting.")
            return [
                ExportOutput(
                    role="mix_mp3",
                    body=mp3,
                    mime="audio/mpeg",
                    processing=f"mp3_{mp3_bitrate}k",
                    sample_rate=probe.sample_rate,
                    channels=probe.channels,
                    duration_seconds=probe.duration_seconds,
                )
            ]
        if output == "stems_wav":
            if stems is None:
                raise RuntimeError("Stems unavailable.")
            built: list[ExportOutput] = []
            for category, body in stems.items():
                probe = probe_wav(body)
                if probe is None:
                    raise RuntimeError(f"Stem {category} is not valid WAV.")
                built.append(
                    ExportOutput(
                        role=f"stem_{category}",
                        body=body,
                        mime="audio/wav",
                        processing=self.separator.name,
                        stem_source="separated",
                        stem_category=category,
                        sample_rate=probe.sample_rate,
                        channels=probe.channels,
                        duration_seconds=probe.duration_seconds,
                    )
                )
            return built
        if output == "stems_zip":
            if stems is None:
                raise RuntimeError("Stems unavailable.")
            manifest = {
                "job_id": job_id,
                "attempt_id": attempt_id,
                "source_version_id": request.get("source_version_id"),
                "stem_source": "separated",
                "separator": self.separator.name,
                "stem_categories": sorted(stems),
                "files": [
                    {
                        "name": f"stems/{category}.wav",
                        "sha256": hashlib.sha256(body).hexdigest(),
                        "bytes": len(body),
                    }
                    for category, body in sorted(stems.items())
                ],
                "created_at": utcnow().isoformat(),
            }
            return [
                ExportOutput(
                    role="stems_zip",
                    body=build_stems_zip(stems, manifest),
                    mime="application/zip",
                    processing=self.separator.name,
                )
            ]
        raise RuntimeError(f"Unknown output {output}.")

    def run_forever(self) -> None:
        self.register()
        while not self._stop:
            try:
                self.run_once()
            except Exception:
                log.exception("audio worker iteration failed")
                time.sleep(2)

    def stop(self) -> None:
        self._stop = True


def tool_version_safe(binary: str) -> str:
    try:
        return tool_version(binary)
    except AudioToolError:
        return "unknown"


def build_audio_worker() -> AudioWorker:
    settings = get_settings()
    db = Db(settings.database_url)
    queue = RedisQueue(build_redis(settings.redis_url))
    storage = build_storage(settings)
    separator = (
        DemucsSeparator(
            settings.demucs_python,
            settings.demucs_model,
            settings.demucs_device,
            settings.separator_timeout_seconds,
        )
        if settings.demucs_python
        else NullSeparator()
    )
    return AudioWorker(db, queue, storage, settings, separator=separator)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    worker = build_audio_worker()
    print(f"audio export worker {worker.worker_id} consuming {worker.queue_name}")
    try:
        worker.run_forever()
    except KeyboardInterrupt:
        worker.stop()
