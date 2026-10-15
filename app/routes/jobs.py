"""Job admission, owner-scoped reads, cancellation and retry (milestone 1).

No worker consumes jobs yet; admitted jobs persist as ``queued``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from datetime import timedelta, timezone

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..deps import owner_from_request
from ..errors import ApiError
from ..models import Asset, Job, JobEvent, IdempotencyRecord, new_uuid, utcnow
from ..orchestration import append_event, as_utc, enqueue
from ..registry import MODEL_RELEASES, SUPPORTED_OPERATIONS
from ..storage import parse_range
from ..tokens import check_token, make_token
from ..schemas import (
    ArtifactsResponse,
    CancelResponse,
    GenerateJobRequest,
    JobAcceptedResponse,
    JobDetailResponse,
    JobPage,
)

router = APIRouter(tags=["jobs"])

CREATE_ROUTE = "POST /jobs"
TERMINAL_STATES = ("succeeded", "failed", "cancelled")


def _job_urls(job_id: str) -> tuple[str, str]:
    base = f"/api/v1/jobs/{job_id}"
    return base, f"{base}/events"


def _detail(job: Job, poll_after: int) -> JobDetailResponse:
    status_url, events_url = _job_urls(job.id)
    return JobDetailResponse(
        job_id=job.id,
        status=job.status,
        operation=job.operation,
        model_id=job.model_id,
        model_revision=job.model_revision,
        attempt_number=job.attempt_number,
        stage=job.stage,
        progress=job.progress,
        progress_source=job.progress_source,
        lyrics_sha256=job.lyrics_sha256,
        lyrics_origin=job.lyrics_origin,
        client_reference=job.client_reference,
        error_code=job.error_code,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        assets_expired_at=job.assets_expired_at,
        status_url=status_url,
        events_url=events_url,
        poll_after_seconds=poll_after,
        required_notices=[],
    )


def _get_owned_job(session: Session, job_id: str, owner_id: str) -> Job:
    job = session.execute(select(Job).where(Job.id == job_id)).scalar_one_or_none()
    if job is None or job.owner_id != owner_id:
        raise ApiError(404, "JOB_NOT_FOUND", "Job not found.")
    return job


def _validate_request(payload: GenerateJobRequest, max_lyrics_chars: int) -> None:
    if payload.operation not in SUPPORTED_OPERATIONS:
        raise ApiError(
            422,
            "OPERATION_UNSUPPORTED",
            f"Operation '{payload.operation}' is not supported by this backend.",
            {"supported_operations": list(SUPPORTED_OPERATIONS)},
        )
    release = MODEL_RELEASES.get(payload.model_id)
    if release is None:
        raise ApiError(
            422,
            "MODEL_UNKNOWN",
            "Unknown model id.",
            {"known_models": sorted(MODEL_RELEASES)},
        )
    if not release.enabled:
        raise ApiError(
            503,
            "MODEL_UNAVAILABLE",
            "The requested model is configured but not accepting jobs.",
            {"model_id": release.model_id},
        )
    if payload.lyrics is not None and len(payload.lyrics) > max_lyrics_chars:
        raise ApiError(
            422,
            "LYRICS_TOO_LONG",
            "Lyrics exceed the configured maximum length.",
            {"max_chars": max_lyrics_chars},
        )
    if not payload.instrumental:
        if payload.lyrics is None or not payload.lyrics.strip():
            raise ApiError(
                422,
                "LYRICS_REQUIRED",
                "Non-instrumental jobs require non-empty lyrics.",
            )
    elif payload.lyrics:
        raise ApiError(
            422,
            "LYRICS_NOT_ALLOWED",
            "Instrumental jobs must not supply lyrics.",
        )
    unknown_controls = sorted(set(payload.controls) - set(release.supported_controls))
    if unknown_controls:
        raise ApiError(
            422,
            "CONTROL_UNSUPPORTED",
            "Unknown or unsupported controls supplied.",
            {"unknown_controls": unknown_controls, "supported_controls": list(release.supported_controls)},
        )
    if payload.seed is not None and not release.supports_seed:
        raise ApiError(422, "CONTROL_UNSUPPORTED", "This model does not accept a seed.")
    if payload.duration_seconds is not None:
        if not release.supports_duration:
            raise ApiError(422, "CONTROL_UNSUPPORTED", "This model does not accept a duration target.")
        if not (release.min_duration_seconds <= payload.duration_seconds <= release.max_duration_seconds):
            raise ApiError(
                422,
                "CONTROL_UNSUPPORTED",
                "Requested duration is outside the model range.",
                {
                    "min_duration_seconds": release.min_duration_seconds,
                    "max_duration_seconds": release.max_duration_seconds,
                },
            )


def _idempotency_key(request: Request, max_length: int) -> str:
    key = request.headers.get("Idempotency-Key")
    if key is None or not key.strip():
        raise ApiError(422, "IDEMPOTENCY_KEY_REQUIRED", "An Idempotency-Key header is required.")
    key = key.strip()
    if len(key) > max_length:
        raise ApiError(
            422,
            "IDEMPOTENCY_KEY_INVALID",
            "Idempotency-Key exceeds the maximum length.",
            {"max_length": max_length},
        )
    return key


@router.post("/jobs", status_code=202, response_model=JobAcceptedResponse)
def create_job(
    payload: GenerateJobRequest,
    request: Request,
    owner_id: str = Depends(owner_from_request),
) -> JSONResponse:
    settings = request.app.state.settings
    _validate_request(payload, settings.max_lyrics_chars)
    key = _idempotency_key(request, settings.max_idempotency_key_length)
    request_hash = payload.request_hash()
    status_url, events_url = None, None

    with request.app.state.db.session() as session:
        existing = session.execute(
            select(IdempotencyRecord).where(
                IdempotencyRecord.owner_id == owner_id,
                IdempotencyRecord.route == CREATE_ROUTE,
                IdempotencyRecord.key == key,
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ApiError(
                    409,
                    "IDEMPOTENCY_CONFLICT",
                    "Idempotency-Key was already used with a different request.",
                    {"job_id": existing.job_id},
                )
            job = _get_owned_job(session, existing.job_id, owner_id)
        else:
            job = Job(
                id=new_uuid(),
                owner_id=owner_id,
                operation=payload.operation,
                model_id=payload.model_id,
                model_revision=MODEL_RELEASES[payload.model_id].revision,
                status="queued",
                request_json=payload.model_dump(mode="json"),
                request_hash=request_hash,
                lyrics=payload.lyrics,
                lyrics_sha256=(
                    hashlib.sha256(payload.lyrics.encode("utf-8")).hexdigest()
                    if payload.lyrics is not None
                    else None
                ),
                lyrics_origin=payload.lyrics_origin,
                client_reference=payload.client_reference,
                idempotency_key=key,
            )
            record = IdempotencyRecord(
                owner_id=owner_id,
                route=CREATE_ROUTE,
                key=key,
                request_hash=request_hash,
                job_id=job.id,
                expires_at=utcnow() + timedelta(hours=settings.idempotency_retention_hours),
            )
            session.add(job)
            session.add(record)
            enqueue(session, job, settings)
            append_event(session, job.id, "queued", "queued")
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                existing = session.execute(
                    select(IdempotencyRecord).where(
                        IdempotencyRecord.owner_id == owner_id,
                        IdempotencyRecord.route == CREATE_ROUTE,
                        IdempotencyRecord.key == key,
                    )
                ).scalar_one_or_none()
                if existing is None:
                    raise ApiError(
                        409,
                        "CONCURRENT_SUBMIT",
                        "Concurrent submission conflict; retry the request.",
                    )
                if existing.request_hash != request_hash:
                    raise ApiError(
                        409,
                        "IDEMPOTENCY_CONFLICT",
                        "Idempotency-Key was already used with a different request.",
                        {"job_id": existing.job_id},
                    )
                job = _get_owned_job(session, existing.job_id, owner_id)

    status_url, events_url = _job_urls(job.id)
    body = JobAcceptedResponse(
        job_id=job.id,
        status=job.status,
        model_id=job.model_id,
        model_revision=job.model_revision,
        status_url=status_url,
        events_url=events_url,
        poll_after_seconds=settings.poll_after_seconds,
        required_notices=[],
    )
    return JSONResponse(status_code=202, content=body.model_dump(mode="json"), headers={"Location": status_url})


@router.get("/jobs", response_model=JobPage)
def list_jobs(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
    owner_id: str = Depends(owner_from_request),
) -> JobPage:
    with request.app.state.db.session() as session:
        stmt = select(Job).where(Job.owner_id == owner_id).order_by(Job.seq.desc()).limit(limit + 1)
        if cursor is not None:
            try:
                after_seq = int(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("ascii"))
            except ValueError:
                raise ApiError(422, "CURSOR_INVALID", "Cursor is not a valid opaque value.")
            stmt = stmt.where(Job.seq < after_seq)
        rows = list(session.execute(stmt).scalars())
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = base64.urlsafe_b64encode(str(rows[-1].seq).encode("ascii")).decode("ascii")
    poll = request.app.state.settings.poll_after_seconds
    return JobPage(jobs=[_detail(job, poll) for job in rows], next_cursor=next_cursor)


@router.get("/jobs/{job_id}", response_model=JobDetailResponse)
def get_job(
    job_id: str,
    request: Request,
    owner_id: str = Depends(owner_from_request),
) -> JobDetailResponse:
    with request.app.state.db.session() as session:
        job = _get_owned_job(session, job_id, owner_id)
    return _detail(job, request.app.state.settings.poll_after_seconds)


@router.post("/jobs/{job_id}/cancel", response_model=CancelResponse)
def cancel_job(
    job_id: str,
    request: Request,
    owner_id: str = Depends(owner_from_request),
) -> CancelResponse:
    with request.app.state.db.session() as session:
        job = _get_owned_job(session, job_id, owner_id)
        transitioned = False
        if job.status == "queued":
            job.status = "cancelled"
            job.cancel_requested_at = utcnow()
            job.finished_at = utcnow()
            transitioned = True
        elif job.status == "running":
            job.status = "cancelling"
            job.cancel_requested_at = utcnow()
            transitioned = True
        elif job.status in ("cancelling", "cancelled"):
            pass
        elif job.status in TERMINAL_STATES:
            raise ApiError(
                409,
                "STATE_CONFLICT",
                f"Job in state '{job.status}' cannot be cancelled.",
                {"status": job.status},
            )
        if transitioned:
            append_event(session, job.id, job.status, job.status)
        session.commit()
        return CancelResponse(
            job_id=job.id,
            status=job.status,
            upstream_termination_supported=False,
        )


@router.post("/jobs/{job_id}/retry", response_model=JobDetailResponse)
def retry_job(
    job_id: str,
    request: Request,
    owner_id: str = Depends(owner_from_request),
) -> JobDetailResponse:
    with request.app.state.db.session() as session:
        job = _get_owned_job(session, job_id, owner_id)
        if job.status not in ("failed", "cancelled"):
            raise ApiError(
                409,
                "STATE_CONFLICT",
                f"Job in state '{job.status}' cannot be retried.",
                {"status": job.status},
            )
        job.status = "queued"
        job.attempt_number += 1
        job.error_code = None
        job.error_message = None
        job.started_at = None
        job.finished_at = None
        job.cancel_requested_at = None
        job.stage = None
        job.progress = None
        enqueue(session, job, request.app.state.settings)
        append_event(session, job.id, "requeued", "queued", message="Explicit retry.")
        session.commit()
    return _detail(job, request.app.state.settings.poll_after_seconds)


@router.get("/jobs/{job_id}/artifacts", response_model=ArtifactsResponse)
def job_artifacts(
    job_id: str,
    request: Request,
    owner_id: str = Depends(owner_from_request),
) -> ArtifactsResponse:
    with request.app.state.db.session() as session:
        job = _get_owned_job(session, job_id, owner_id)
        assets = list(
            session.execute(
                select(Asset)
                .where(Asset.job_id == job.id, Asset.deleted_at.is_(None))
                .order_by(Asset.created_at)
            ).scalars()
        )
    return ArtifactsResponse(
        job_id=job.id,
        artifacts=[
            {
                "asset_id": asset.id,
                "role": asset.role,
                "kind": asset.kind,
                "source_asset_id": asset.source_asset_id,
                "stem_source": asset.stem_source,
                "stem_category": asset.stem_category,
                "processing": asset.processing,
                "mime": asset.mime,
                "bytes": asset.bytes,
                "sha256": asset.sha256,
                "sample_rate": asset.sample_rate,
                "channels": asset.channels,
                "duration_seconds": asset.duration_seconds,
                "synthetic_test_audio": asset.synthetic,
                "expires_at": asset.expires_at.isoformat() if asset.expires_at else None,
            }
            for asset in assets
        ],
    )


@router.get("/jobs/{job_id}/events")
def job_events(
    job_id: str,
    request: Request,
    owner_id: str = Depends(owner_from_request),
) -> StreamingResponse:
    settings = request.app.state.settings
    with request.app.state.db.session() as session:
        _get_owned_job(session, job_id, owner_id)
    last_event_header = request.headers.get("Last-Event-ID")
    last_id = 0
    if last_event_header:
        try:
            last_id = int(last_event_header.rsplit("-", 1)[-1])
        except ValueError:
            last_id = 0

    def _fetch(after: int):
        with request.app.state.db.session() as session:
            job = _get_owned_job(session, job_id, owner_id)
            rows = list(
                session.execute(
                    select(JobEvent).where(JobEvent.job_id == job.id, JobEvent.id > after).order_by(JobEvent.id)
                ).scalars()
            )
            return job.status, rows

    def _sse(event: JobEvent) -> str:
        data = json.dumps(
            {
                "job_id": event.job_id,
                "attempt_id": event.attempt_id,
                "event": event.event,
                "status": event.status,
                "stage": event.stage,
                "progress": event.progress,
                "message": event.message,
            }
        )
        return f"id: {event.job_id}-{event.id}\nevent: {event.event}\ndata: {data}\n\n"

    def _stream():
        cursor = last_id
        deadline = time.monotonic() + settings.sse_follow_seconds
        while True:
            status, rows = _fetch(cursor)
            for event in rows:
                cursor = event.id
                yield _sse(event)
            if status in TERMINAL_STATES or not rows and time.monotonic() > deadline:
                if status in TERMINAL_STATES:
                    return
                yield "event: resync\ndata: {}\n\n"
                return
            time.sleep(0.25)

    return StreamingResponse(_stream(), media_type="text/event-stream")


@router.post("/artifacts/{asset_id}/download-url")
def artifact_download_url(
    asset_id: str,
    request: Request,
    owner_id: str = Depends(owner_from_request),
) -> JSONResponse:
    settings = request.app.state.settings
    with request.app.state.db.session() as session:
        asset = session.execute(select(Asset).where(Asset.id == asset_id)).scalar_one_or_none()
        if asset is None or asset.owner_id != owner_id:
            raise ApiError(404, "ASSET_NOT_FOUND", "Asset not found.")
        now = utcnow()
        if asset.deleted_at is not None or (as_utc(asset.expires_at) is not None and as_utc(asset.expires_at) <= now):
            raise ApiError(410, "ASSET_EXPIRED", "Asset retention has expired.")
        expiry = now + timedelta(seconds=settings.download_url_ttl_seconds)
        if asset.expires_at is not None and as_utc(asset.expires_at) < expiry:
            expiry = as_utc(asset.expires_at)
        token = make_token(settings.secret_key, asset.id, expiry)
    return JSONResponse(
        status_code=200,
        content={
            "asset_id": asset.id,
            "url": f"/api/v1/artifacts/{asset.id}/content?token={token}",
            "expires_at": expiry.isoformat(),
        },
    )


@router.get("/artifacts/{asset_id}/content")
def artifact_content(
    asset_id: str,
    request: Request,
    token: str = Query(...),
) -> Response:
    settings = request.app.state.settings
    with request.app.state.db.session() as session:
        asset = session.execute(select(Asset).where(Asset.id == asset_id)).scalar_one_or_none()
    if asset is None:
        raise ApiError(404, "ASSET_NOT_FOUND", "Asset not found.")
    now = utcnow()
    if asset.deleted_at is not None or (as_utc(asset.expires_at) is not None and as_utc(asset.expires_at) <= now):
        raise ApiError(410, "ASSET_EXPIRED", "Asset retention has expired.")
    expiry = check_token(settings.secret_key, asset.id, token, now)
    if expiry is None:
        raise ApiError(403, "DOWNLOAD_TOKEN_INVALID", "Download token is invalid or expired.")
    byte_range = parse_range(request.headers.get("Range"), asset.bytes)
    stored = request.app.state.storage.get(asset.storage_key, byte_range)
    headers = {"Accept-Ranges": "bytes"}
    status_code = 200
    if stored.content_range is not None:
        headers["Content-Range"] = stored.content_range
        status_code = 206
    return Response(
        content=stored.body,
        status_code=status_code,
        media_type=asset.mime,
        headers=headers,
    )
