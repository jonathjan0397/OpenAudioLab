"""Durable orchestration: outbox dispatch, claims, leases, reconciliation.

Database records are authoritative; Redis messages are delivery hints.
Cancellation beats late completion: a result that arrives after the job left
``running`` is discarded and cannot publish assets.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from .config import Settings
from .db import Db
from .models import (
    Asset,
    Job,
    JobAttempt,
    JobEvent,
    OutboxRecord,
    utcnow,
)
from .queue import RedisQueue
from .storage import Storage

log = logging.getLogger("oal.orchestration")

TERMINAL_JOB_STATUSES = ("succeeded", "failed", "cancelled")

# Recovery policy (docs/REMEDIATION_PLAN.md §C). Infrastructure failures are
# retryable within the attempt budget; resource failures additionally mark the
# worker unhealthy (the caller does that); anything not listed is permanent
# and fails terminally, exactly as before this policy existed.
RETRYABLE_ERROR_CODES = {
    "ENGINE_TIMEOUT",
    "ENGINE_ERROR",
    "ENGINE_UNAVAILABLE",
    "ENGINE_OOM",
    "ENGINE_START_FAILED",
    "STORAGE_UNAVAILABLE",
}
RESOURCE_ERROR_CODES = {"ENGINE_OOM", "ENGINE_START_FAILED"}


def is_retryable(error_code: str | None) -> bool:
    return error_code in RETRYABLE_ERROR_CODES


def retry_backoff(attempt_number: int) -> timedelta:
    """Bounded exponential backoff with jitter; never exceeds 60 s."""
    import random

    base = min(60.0, 5.0 * (2 ** max(0, attempt_number - 1)))
    return timedelta(seconds=base + random.uniform(0, 2))


def refund_generation_credits(session: Session, job: Job | None) -> None:
    """Idempotently refund user generation debits on terminal failure.

    Pairing is by count: every ``generation`` debit may have one matching
    ``generation-refund`` credit (explicit retries re-charge, so a retried job
    can legitimately be refunded once per charged attempt).
    """
    if job is None or not job.owner_id.startswith("usr_"):
        return
    from .quota import GENERATION_OPERATIONS
    from .models import CreditEntry, User

    if job.operation not in GENERATION_OPERATIONS:
        return
    entries = list(
        session.execute(
            select(CreditEntry).where(CreditEntry.job_id == job.id,
                                      CreditEntry.reason.in_(("generation", "generation-refund")))
        ).scalars()
    )
    charged = sum(-e.delta for e in entries if e.reason == "generation")
    refunded = sum(e.delta for e in entries if e.reason == "generation-refund")
    outstanding = charged - refunded
    if outstanding <= 0:
        return
    user = session.get(User, job.owner_id[4:])
    if user is None:
        return
    user.credits_balance += outstanding
    session.add(
        CreditEntry(owner_id=job.owner_id, delta=outstanding, reason="generation-refund", job_id=job.id)
    )


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def get_job_by_id(session: Session, job_id: str) -> Job | None:
    """Jobs are addressed by their public UUID, not the internal integer PK."""
    return session.execute(select(Job).where(Job.id == job_id)).scalar_one_or_none()


def append_event(
    session: Session,
    job_id: str,
    event: str,
    status: str,
    stage: str | None = None,
    progress: float | None = None,
    message: str | None = None,
    attempt_id: str | None = None,
) -> JobEvent:
    record = JobEvent(
        job_id=job_id,
        attempt_id=attempt_id,
        event=event,
        status=status,
        stage=stage,
        progress=progress,
        message=message,
    )
    session.add(record)
    return record


def set_job_stage(db: "Db", job_id: str, stage: str, progress: float | None = None) -> None:
    """Best-effort live progress feedback for a running job."""
    with db.session() as session:
        job = session.execute(
            update(Job).where(Job.id == job_id, Job.status == "running").values(stage=stage, progress=progress)
        )
        session.commit()


def set_upstream_task(db: "Db", attempt_id: str, lease_token: str, task_id: str) -> None:
    """Persist the engine task id right after submit (duplicate-inference guard)."""
    with db.session() as session:
        session.execute(
            update(JobAttempt)
            .where(JobAttempt.id == attempt_id, JobAttempt.lease_token == lease_token)
            .values(upstream_task_id=task_id)
        )
        session.commit()


def enqueue(session: Session, job: Job, settings: Settings) -> OutboxRecord:
    record = OutboxRecord(job_id=job.id, queue=RedisQueue.queue_name(job.model_id))
    session.add(record)
    return record


class Dispatcher:
    """Publishes the outbox and reconciles expired leases. Separate process."""

    def __init__(self, db: Db, queue: RedisQueue, settings: Settings) -> None:
        self.db = db
        self.queue = queue
        self.settings = settings

    def publish_once(self, limit: int = 50, reserve: int | None = None) -> int:
        if reserve is None:
            reserve = self.settings.dispatcher_baseline_reserve
        published = 0
        with self.db.session() as session:
            now = utcnow()
            rows = list(
                session.execute(
                    select(OutboxRecord)
                    .join(Job, Job.id == OutboxRecord.job_id)
                    .where(
                        OutboxRecord.published_at.is_(None),
                        or_(Job.next_retry_at.is_(None), Job.next_retry_at <= now),
                    )
                    .order_by(OutboxRecord.id)
                    .limit(limit)
                ).scalars()
            )
            for record in rows:
                # Baseline-first: keep the baseline queue filled up to `reserve`
                # pending jobs; overflow goes to the burst tier (Vast only).
                # Burst exists ONLY for model queues a Vast node can drain;
                # training queues have no burst consumer, and routing stranded
                # re-publishes there silently kills delivery.
                burstable = "ace-step" in record.queue
                target = (
                    record.queue
                    if (not burstable or self.queue.depth(record.queue) < reserve)
                    else RedisQueue.burst_name(record.queue)
                )
                self.queue.publish(target, record.job_id)
                record.published_at = utcnow()
                published += 1
            session.commit()
        return published

    def reconcile_once(self) -> int:
        cutoff = utcnow() - timedelta(seconds=self.settings.lease_seconds)
        handled = 0
        with self.db.session() as session:
            stale = list(
                session.execute(
                    select(JobAttempt).where(
                        JobAttempt.status == "running",
                        JobAttempt.heartbeat_at.is_not(None),
                        JobAttempt.heartbeat_at < cutoff,
                    )
                ).scalars()
            )
            for attempt in stale:
                handled += 1
                attempt.status = "interrupted"
                attempt.finished_at = utcnow()
                job = get_job_by_id(session, attempt.job_id)
                if job is None or job.status not in ("running", "cancelling"):
                    continue
                from .quota import release_guest_reservation

                if job.cancel_requested_at is not None:
                    job.status = "cancelled"
                    job.finished_at = utcnow()
                    release_guest_reservation(session, job, "worker_cancelled")
                    append_event(session, job.id, "cancelled", "cancelled", attempt_id=attempt.id)
                elif job.attempt_number >= self.settings.max_attempts:
                    job.status = "failed"
                    job.finished_at = utcnow()
                    job.error_code = "MAX_ATTEMPTS"
                    job.error_message = "Attempt budget exhausted after worker interruption."
                    release_guest_reservation(session, job, "worker_failed")
                    refund_generation_credits(session, job)
                    append_event(session, job.id, "failed", "failed", message="MAX_ATTEMPTS", attempt_id=attempt.id)
                else:
                    job.attempt_number += 1
                    job.status = "queued"
                    job.stage = None
                    job.progress = None
                    enqueue(session, job, self.settings)
                    append_event(
                        session,
                        job.id,
                        "requeued",
                        "queued",
                        message="Worker lease expired; new attempt queued.",
                        attempt_id=attempt.id,
                    )
            session.commit()
        return handled

    def republish_stranded_once(self, limit: int = 20, grace_seconds: float | None = None) -> int:
        """Re-publish queued jobs whose Redis message was lost after publish.

        A BRPOP that dies before the DB claim destroys the message; the job
        stays ``queued`` with no delivery hint. After a grace window (so we do
        not spam legitimately-queued jobs on busy queues) the job gets a fresh
        outbox row; duplicate deliveries stay harmless via the claim guard.
        """
        grace = grace_seconds if grace_seconds is not None else self.settings.dispatcher_stranded_grace_seconds
        cutoff = utcnow() - timedelta(seconds=grace)
        handled = 0
        with self.db.session() as session:
            jobs = list(
                session.execute(
                    select(Job)
                    .where(Job.status == "queued", Job.updated_at < cutoff)
                    .order_by(Job.seq)
                    .limit(limit)
                ).scalars()
            )
            for job in jobs:
                if job.next_retry_at is not None and as_utc(job.next_retry_at) > utcnow():
                    continue
                latest = session.execute(
                    select(OutboxRecord)
                    .where(OutboxRecord.job_id == job.id)
                    .order_by(OutboxRecord.id.desc())
                    .limit(1)
                ).scalars().first()
                if latest is None or latest.published_at is None:
                    continue  # publish_once still owns this job
                running = session.execute(
                    select(JobAttempt.id)
                    .where(JobAttempt.job_id == job.id, JobAttempt.status == "running")
                    .limit(1)
                ).scalars().first()
                if running is not None:
                    continue
                enqueue(session, job, self.settings)
                job.updated_at = utcnow()  # re-arm the grace window for this sweep
                append_event(session, job.id, "requeued", "queued", message="Stranded queued job re-published.")
                handled += 1
            session.commit()
        return handled

    def run_forever(self) -> None:
        while True:
            try:
                self.publish_once()
                self.reconcile_once()
                self.republish_stranded_once()
            except Exception:  # pragma: no cover - process supervisor boundary
                log.exception("dispatcher iteration failed")
            time.sleep(self.settings.dispatcher_poll_seconds)


def claim_attempt(db: Db, job_id: str, worker_id: str) -> tuple[str, str, str] | None:
    """Claim a queued job for one attempt. Returns (job_id, attempt_id, lease_token).

    Duplicate deliveries and cancelled jobs lose the race and return None.
    """
    with db.session() as session:
        job = session.execute(
            select(Job).where(Job.id == job_id).with_for_update()
        ).scalar_one_or_none()
        if job is None or job.status != "queued":
            return None
        if job.next_retry_at is not None and as_utc(job.next_retry_at) > utcnow():
            return None  # early duplicate delivery; the sweeper re-publishes later
        existing = session.execute(
            select(JobAttempt).where(
                JobAttempt.job_id == job.id,
                JobAttempt.attempt_number == job.attempt_number,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return None
        token = uuid4().hex
        attempt = JobAttempt(
            job_id=job.id,
            attempt_number=job.attempt_number,
            worker_id=worker_id,
            lease_token=token,
            status="running",
            heartbeat_at=utcnow(),
        )
        session.add(attempt)
        job.status = "running"
        job.next_retry_at = None
        job.started_at = utcnow()
        job.stage = "accepted"
        append_event(session, job.id, "running", "running", stage="accepted", attempt_id=attempt.id)
        session.commit()
        return job.id, attempt.id, token


def heartbeat(db: Db, attempt_id: str, lease_token: str) -> bool:
    with db.session() as session:
        result = session.execute(
            update(JobAttempt)
            .where(
                JobAttempt.id == attempt_id,
                JobAttempt.lease_token == lease_token,
                JobAttempt.status == "running",
            )
            .values(heartbeat_at=utcnow())
        )
        session.commit()
        return result.rowcount > 0


def is_cancelling(db: Db, job_id: str) -> bool:
    with db.session() as session:
        job = session.execute(select(Job).where(Job.id == job_id)).scalar_one_or_none()
        return job is not None and job.status == "cancelling"


def _finish_attempt(session: Session, attempt_id: str, lease_token: str, status: str) -> bool:
    result = session.execute(
        update(JobAttempt)
        .where(
            JobAttempt.id == attempt_id,
            JobAttempt.lease_token == lease_token,
            JobAttempt.status == "running",
        )
        .values(status=status, finished_at=utcnow())
    )
    return result.rowcount > 0


def _generation_manifest(
    job: Job,
    attempt_id: str,
    engine_payload: dict | None,
    engine_result: dict | None,
    engine_version: str | None,
    synthetic: bool,
) -> dict:
    request = dict(job.request_json or {})
    admission = dict(request.get("_admission") or {})
    controls = dict(request.get("controls") or {})
    engine_payload = dict(engine_payload or {})
    engine_result = dict(engine_result or {})
    seed = engine_result.get("seed") or engine_payload.get("seed") or request.get("seed")
    return {
        "schema_version": "oal.generation.v1",
        "job_id": job.id,
        "attempt_id": attempt_id,
        "created_at": utcnow().isoformat(),
        "requested": {
            "operation": job.operation,
            "model_id": job.model_id,
            "model_selection": admission.get("model_selection", job.model_id),
            "execution_profile_id": admission.get("execution_profile_id"),
            "engine_model": admission.get("engine_model"),
            "planner_model": admission.get("planner_model"),
            "family": admission.get("family"),
            "model_revision": job.model_revision,
            "music_description": request.get("music_description"),
            "song_idea": request.get("song_idea"),
            "style_prompt": request.get("style_prompt"),
            "title": request.get("title"),
            "lyrics_sha256": job.lyrics_sha256,
            "lyrics_origin": job.lyrics_origin,
            "instrumental": request.get("instrumental"),
            "duration_seconds": request.get("duration_seconds"),
            "seed": request.get("seed"),
            "controls": controls,
            "outputs": request.get("outputs") or [],
            "voice": request.get("_voice"),
            "lora_id": request.get("lora_id"),
            "client_reference": job.client_reference,
            "task_type": request.get("task_type") or "text2music",
            "src_asset_id": request.get("src_asset_id"),
            "reference_asset_id": request.get("reference_asset_id"),
            "audio_cover_strength": request.get("audio_cover_strength"),
            "cover_noise_strength": request.get("cover_noise_strength"),
            "repainting_start": request.get("repainting_start"),
            "repainting_end": request.get("repainting_end"),
            "repaint_mode": request.get("repaint_mode"),
            "repaint_strength": request.get("repaint_strength"),
            "chunk_mask_mode": request.get("chunk_mask_mode"),
        },
        "resolved": {
            "lyrics": job.lyrics,
            "lyrics_sha256": job.lyrics_sha256,
            "seed": seed,
            "controls": controls,
            "engine_payload": engine_payload,
        },
        "effective": {
            "engine_version": engine_version,
            "seed": seed,
            "synthetic": synthetic,
            "pricing": {
                "policy_version": admission.get("policy_version"),
                "quote_id": admission.get("quote_id"),
                "reserved_credits": admission.get("reserved_credits"),
            },
            "upstream": {
                "task_id": engine_result.get("task_id"),
                "dit_model": engine_result.get("dit_model"),
                "duration_seconds": engine_result.get("duration_seconds"),
            },
        },
    }


def complete_attempt(
    db: Db,
    storage: Storage,
    settings: Settings,
    job_id: str,
    attempt_id: str,
    lease_token: str,
    artifact: tuple[str, bytes],
    audio_meta: tuple[int, int, float] | None = None,
    synthetic: bool = True,
    engine_version: str | None = None,
    engine_payload: dict | None = None,
    engine_result: dict | None = None,
) -> str:
    """Complete a running attempt with one artifact (role, body).

    Returns ``succeeded``, ``discarded`` (cancellation won) or ``stale``
    (lease already lost; the result may not publish).
    """
    artifacts = artifact if isinstance(artifact, list) else [(*artifact, audio_meta)]
    with db.session() as session:
        if not _finish_attempt(session, attempt_id, lease_token, "succeeded"):
            append_event(session, job_id, "discarded", "stale-lease", message="Lease lost before completion.", attempt_id=attempt_id)
            session.commit()
            return "stale"
        if engine_version is not None:
            attempt = session.get(JobAttempt, attempt_id)
            if attempt is not None:
                attempt.engine_version = engine_version
        result = session.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == "running")
            .values(
                status="succeeded",
                finished_at=utcnow(),
                stage="done",
                progress=1.0,
                progress_source="fixture" if synthetic else "engine",
            )
        )
        if result.rowcount == 0:
            job = get_job_by_id(session, job_id)
            if job is not None and job.status == "cancelling":
                job.status = "cancelled"
                job.finished_at = utcnow()
            attempt = session.get(JobAttempt, attempt_id)
            if attempt is not None:
                attempt.status = "discarded"
            append_event(session, job_id, "discarded", job.status if job else "unknown", message="Late completion discarded after cancellation.", attempt_id=attempt_id)
            session.commit()
            return "discarded"
        job = get_job_by_id(session, job_id)
        expires_at = utcnow() + timedelta(days=settings.asset_retention_days)
        base_manifest = _generation_manifest(job, attempt_id, engine_payload, engine_result, engine_version, synthetic)
        controls = dict(job.request_json.get("controls") or {})
        mood = controls.get("mood")
        gender = {"male": "male vocals", "female": "female vocals"}.get(controls.get("gender"))
        tags = [t for t in [mood, gender] if t]
        req_title = (job.request_json.get("title") or "").strip() or None
        for index, (role_name, data, meta) in enumerate(artifacts):
            suffix = "" if index == 0 else f"-{index + 1}"
            key = f"owners/{job.owner_id}/jobs/{job.id}/{attempt_id}/{role_name}{suffix}.wav"
            checksum = storage.put(key, data)
            try:
                from .peaks import peaks_json

                storage.put(key[: -len(".wav")] + ".json", peaks_json(data))
            except Exception:  # waveform peaks are best-effort decoration
                pass
            asset = Asset(
                job_id=job.id,
                owner_id=job.owner_id,
                attempt_id=attempt_id,
                workspace_id=(job.request_json or {}).get("workspace_id"),
                storage_key=key,
                role=role_name,
                mime="audio/wav",
                bytes=len(data),
                sha256=checksum,
                synthetic=synthetic,
                tags_json=list(tags),
                manifest_json={
                    **base_manifest,
                    "artifact": {
                        "role": role_name,
                        "index": index,
                        "storage_key": key,
                        "sha256": checksum,
                        "bytes": len(data),
                        "mime": "audio/wav",
                        "sample_rate": meta[0] if meta else None,
                        "channels": meta[1] if meta else None,
                        "duration_seconds": round(meta[2], 3) if meta else None,
                    },
                },
                title=(
                    (req_title if len(artifacts) == 1 else f"{req_title} (Take {index + 1})")
                    if req_title
                    else (f"Take {index + 1}" if len(artifacts) > 1 else None)
                ),
                finalized_at=utcnow(),
                expires_at=expires_at,
                sample_rate=meta[0] if meta else None,
                channels=meta[1] if meta else None,
                duration_seconds=round(meta[2], 3) if meta else None,
            )
            if role_name == "mix_wav":
                from .naming import assign_asset_slug

                assign_asset_slug(session, asset)
            session.add(asset)
        job.assets_expired_at = expires_at
        from .quota import commit_guest_reservation

        commit_guest_reservation(session, job)
        append_event(session, job.id, "succeeded", "succeeded", stage="done", progress=1.0, attempt_id=attempt_id)
        session.commit()
        return "succeeded"


def fail_attempt(
    db: Db,
    settings: Settings,
    job_id: str,
    attempt_id: str,
    lease_token: str,
    error_code: str,
    error_message: str,
    component: str = "worker",
) -> str:
    from .errorlog import record_error

    record_error(
        db,
        component=component,
        error_code=error_code,
        message=error_message,
        job_id=job_id,
    )
    with db.session() as session:
        if not _finish_attempt(session, attempt_id, lease_token, "failed"):
            session.commit()
            return "stale"
        job = get_job_by_id(session, job_id)
        requeued = False
        if job is not None and job.status in ("running", "cancelling"):
            if job.cancel_requested_at is not None:
                job.status = "cancelled"
                job.finished_at = utcnow()
            elif is_retryable(error_code) and job.attempt_number < settings.max_attempts:
                # Bounded automatic retry for infrastructure failures: the
                # attempt budget still applies and backoff paces the requeue.
                job.attempt_number += 1
                job.status = "queued"
                job.stage = None
                job.progress = None
                job.error_code = error_code
                job.error_message = error_message
                job.next_retry_at = utcnow() + retry_backoff(job.attempt_number)
                enqueue(session, job, settings)
                requeued = True
            else:
                job.status = "failed"
                job.error_code = error_code
                job.error_message = error_message
                job.finished_at = utcnow()
        from .quota import release_guest_reservation

        if job is not None and job.status in TERMINAL_JOB_STATUSES:
            release_guest_reservation(session, job, "job_failed")
            refund_generation_credits(session, job)
        append_event(session, job_id, "requeued" if requeued else "failed",
                     job.status if job else "unknown", message=error_code, attempt_id=attempt_id)
        session.commit()
        return "requeued" if requeued else "failed"


def cancel_attempt(db: Db, job_id: str, attempt_id: str, lease_token: str) -> str:
    """Cooperative cancellation observed by the worker mid-run."""
    with db.session() as session:
        if not _finish_attempt(session, attempt_id, lease_token, "cancelled"):
            session.commit()
            return "stale"
        job = get_job_by_id(session, job_id)
        if job is not None and job.status in ("running", "cancelling"):
            job.status = "cancelled"
            job.finished_at = utcnow()
        from .quota import release_guest_reservation

        if job is not None and job.status in TERMINAL_JOB_STATUSES:
            release_guest_reservation(session, job, "job_cancelled")
        append_event(session, job_id, "cancelled", "cancelled", attempt_id=attempt_id)
        session.commit()
        return "cancelled"
