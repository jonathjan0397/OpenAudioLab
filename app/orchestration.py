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

from sqlalchemy import select, update
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
            rows = list(
                session.execute(
                    select(OutboxRecord)
                    .where(OutboxRecord.published_at.is_(None))
                    .order_by(OutboxRecord.id)
                    .limit(limit)
                ).scalars()
            )
            for record in rows:
                # Baseline-first: keep the baseline queue filled up to `reserve`
                # pending jobs; overflow goes to the burst tier (Vast only).
                target = (
                    record.queue
                    if self.queue.depth(record.queue) < reserve
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
                if job.cancel_requested_at is not None:
                    job.status = "cancelled"
                    job.finished_at = utcnow()
                    append_event(session, job.id, "cancelled", "cancelled", attempt_id=attempt.id)
                elif job.attempt_number >= self.settings.max_attempts:
                    job.status = "failed"
                    job.finished_at = utcnow()
                    job.error_code = "MAX_ATTEMPTS"
                    job.error_message = "Attempt budget exhausted after worker interruption."
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

    def run_forever(self) -> None:
        while True:
            try:
                self.publish_once()
                self.reconcile_once()
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
                storage_key=key,
                role=role_name,
                mime="audio/wav",
                bytes=len(data),
                sha256=checksum,
                synthetic=synthetic,
                tags_json=list(tags),
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
            session.add(asset)
        job.assets_expired_at = expires_at
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
        if job is not None and job.status in ("running", "cancelling"):
            if job.cancel_requested_at is not None:
                job.status = "cancelled"
            else:
                job.status = "failed"
                job.error_code = error_code
                job.error_message = error_message
            job.finished_at = utcnow()
        append_event(session, job_id, "failed", job.status if job else "unknown", message=error_code, attempt_id=attempt_id)
        session.commit()
        return "failed"


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
        append_event(session, job_id, "cancelled", "cancelled", attempt_id=attempt_id)
        session.commit()
        return "cancelled"
