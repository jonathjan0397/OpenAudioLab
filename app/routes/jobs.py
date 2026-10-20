"""Job admission, owner-scoped reads, cancellation and retry (milestone 1).

No worker consumes jobs yet; admitted jobs persist as ``queued``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import random
import time
from datetime import timedelta, timezone

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..deps import owner_from_request
from ..errors import ApiError
from ..models import Asset, GuestSession, Job, JobEvent, IdempotencyRecord, new_uuid, utcnow
from ..orchestration import append_event, as_utc, enqueue
from ..registry import MODEL_RELEASES, SUPPORTED_OPERATIONS, validate_controls
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
        seed=(job.request_json or {}).get("seed"),
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
    invalid_controls = validate_controls(payload.model_id, payload.controls)
    if invalid_controls:
        raise ApiError(
            422,
            "CONTROL_INVALID",
            "One or more control values are out of range or the wrong type.",
            {
                "invalid_controls": invalid_controls,
                "supported_controls": list(release.supported_controls),
            },
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


def _auto_lora_match(session: Session, payload: GenerateJobRequest) -> dict | None:
    """M14c hybrid auto-apply: tag-overlap match against active auto-apply LoRAs."""
    import re

    from ..models import Lora

    controls = dict(payload.controls or {})
    text = f"{controls.get('mood') or ''} {payload.music_description or ''}"
    words = {re.sub(r"[^a-z0-9&-]", "", w.lower()) for w in re.split(r"[,\s]+", text)}
    words.discard("")
    if not words:
        return None
    best, best_score, best_tags = None, 0, []
    for lora in session.execute(
        select(Lora).where(Lora.state == "active", Lora.auto_apply.is_(True))
    ).scalars():
        tags = {str(t).lower().strip() for t in (lora.tags_json or [])}
        matched = sorted(words & tags)
        if len(matched) > best_score or (
            matched and best is not None and len(matched) == best_score and lora.priority > best.priority
        ):
            best, best_score, best_tags = lora, len(matched), matched
    if best is None:
        return None
    return {"lora_id": best.id, "lora_match": {"mode": "auto", "name": best.name, "tags": best_tags}}


@router.post("/jobs", status_code=202, response_model=JobAcceptedResponse)
def create_job(
    payload: GenerateJobRequest,
    request: Request,
    owner_id: str = Depends(owner_from_request),
) -> JSONResponse:
    from ..deps import guest_session_from_request
    from ..policies import current_policy_payload, record_policy_acceptance
    from ..quota import GENERATION_OPERATIONS, guest_id_from_owner, is_guest_owner, requested_takes, reserve_guest_quota

    settings = request.app.state.settings
    _validate_request(payload, settings.max_lyrics_chars)
    guest = is_guest_owner(owner_id) and payload.operation in GENERATION_OPERATIONS
    if guest:
        if payload.duration_seconds is not None and payload.duration_seconds > settings.guest_max_duration_seconds:
            raise ApiError(
                422,
                "GUEST_DURATION_EXCEEDED",
                "Guest songs are limited to two minutes.",
                {"max_duration_seconds": settings.guest_max_duration_seconds},
            )
        if payload.duration_seconds is None:
            payload.duration_seconds = settings.guest_max_duration_seconds
    key = _idempotency_key(request, settings.max_idempotency_key_length)
    request_hash = payload.request_hash()
    status_url, events_url = None, None

    with request.app.state.db.session() as session:
        if payload.lora_id is not None and payload.artist_profile_version_id is not None:
            raise ApiError(
                422,
                "LORA_PROFILE_CONFLICT",
                "Choose either a registry LoRA or an artist profile version, not both.",
            )
        if payload.artist_profile_version_id is not None:
            from ..models import ArtistProfileVersion

            profile_version = session.get(ArtistProfileVersion, payload.artist_profile_version_id)
            if profile_version is None or profile_version.owner_id != owner_id:
                raise ApiError(404, "PROFILE_VERSION_NOT_FOUND", "Artist profile version not found.")
            if profile_version.base_model_id != payload.model_id:
                raise ApiError(
                    422,
                    "PROFILE_INCOMPATIBLE",
                    "The profile version was trained for a different base model.",
                    {"profile_base_model_id": profile_version.base_model_id, "model_id": payload.model_id},
                )
            if profile_version.state not in ("active", "candidate"):
                raise ApiError(409, "STATE_CONFLICT", "Retired profile versions cannot be used for new jobs.")
        if payload.lora_id is not None:
            from ..models import Lora

            lora = session.get(Lora, payload.lora_id)
            if lora is None or lora.state != "active":
                raise ApiError(404, "LORA_NOT_FOUND", "Active registry LoRA not found.")
            if lora.base_model_id != payload.model_id:
                raise ApiError(
                    422,
                    "LORA_INCOMPATIBLE",
                    "The registry LoRA was trained for a different base model.",
                    {"lora_base_model_id": lora.base_model_id, "model_id": payload.model_id},
                )
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
            request_json = payload.model_dump(mode="json")
            if payload.operation == "music.generate" and request_json.get("seed") is None:
                request_json["seed"] = random.randint(1, 1_000_000_000)
            job = Job(
                id=new_uuid(),
                owner_id=owner_id,
                operation=payload.operation,
                model_id=payload.model_id,
                model_revision=MODEL_RELEASES[payload.model_id].revision,
                status="queued",
                request_json=request_json,
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
            if payload.lora_id is None and payload.operation == "music.generate":
                auto = _auto_lora_match(session, payload)
                if auto is not None:
                    job.request_json = {**job.request_json, **auto}
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
            if guest:
                guest_id = guest_id_from_owner(owner_id)
                guest_row = session.get(GuestSession, guest_id)
                if guest_row is None:
                    raise ApiError(401, "GUEST_NOT_FOUND", "Guest session is missing or expired.")
                if guest_row.policy_accepted_at is None:
                    current_version = current_policy_payload(session, settings)["version"]
                    if not payload.policy_accepted:
                        raise ApiError(
                            403,
                            "POLICY_ACCEPTANCE_REQUIRED",
                            "Guests must accept the Terms, Abuse Policy, and Privacy Notice before generating.",
                        )
                    if payload.policy_version and payload.policy_version != current_version:
                        raise ApiError(422, "POLICY_VERSION_STALE", "Policy terms changed; reload and accept the current terms.")
                    guest_row.policy_version = current_version
                    guest_row.policy_accepted_at = utcnow()
                    guest_row.marketing_consent = payload.marketing_consent
                    record_policy_acceptance(
                        session,
                        "guest",
                        guest_row.id,
                        current_version,
                        marketing_consent=payload.marketing_consent,
                        ip_hash=guest_row.ip_hash,
                        user_agent=guest_row.user_agent,
                    )
                reserve_guest_quota(session, guest_id, job.id, requested_takes(payload.controls), settings)
            if owner_id.startswith("usr_"):
                from ..models import CreditEntry, User

                user = session.get(User, owner_id[4:])
                if user is None:
                    raise ApiError(401, "USER_NOT_FOUND", "Account not found for session owner.")
                cost = settings.credit_cost_per_generation * max(1, min(4, int((payload.controls or {}).get("variations") or 1)))
                if user.credits_balance < cost:
                    raise ApiError(
                        402,
                        "INSUFFICIENT_CREDITS",
                        "Not enough credits for this generation.",
                        {"cost": cost, "balance": user.credits_balance},
                    )
                user.credits_balance -= cost
                session.add(
                    CreditEntry(owner_id=owner_id, delta=-cost, reason="generation", job_id=job.id)
                )
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
            if job.status == "cancelled":
                from ..quota import release_guest_reservation

                release_guest_reservation(session, job, "job_cancelled")
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
        from ..quota import GENERATION_OPERATIONS, guest_id_from_owner, is_guest_owner, requested_takes, reserve_guest_quota

        if is_guest_owner(owner_id) and job.operation in GENERATION_OPERATIONS:
            reserve_guest_quota(
                session,
                guest_id_from_owner(owner_id),
                job.id,
                requested_takes(job.request_json.get("controls")),
                request.app.state.settings,
            )
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
                "title": asset.title,
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
                "manifest": asset.manifest_json or {},
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
    try:
        stored = request.app.state.storage.get(asset.storage_key, byte_range)
    except FileNotFoundError:
        raise ApiError(404, "ASSET_FILE_MISSING", "Stored file is missing.")
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


@router.get("/artifacts/{asset_id}/waveform")
def artifact_waveform(
    asset_id: str,
    request: Request,
    token: str | None = Query(default=None),
) -> Response:
    from ..deps import owner_from_request

    settings = request.app.state.settings
    with request.app.state.db.session() as session:
        asset = session.execute(select(Asset).where(Asset.id == asset_id)).scalar_one_or_none()
    if asset is None:
        raise ApiError(404, "ASSET_NOT_FOUND", "Asset not found.")
    allowed = bool(asset.shared)
    if not allowed and token:
        allowed = check_token(settings.secret_key, asset.id, token, utcnow()) is not None
    if not allowed:
        try:
            allowed = owner_from_request(request) == asset.owner_id
        except ApiError:
            allowed = False
    if not allowed:
        raise ApiError(403, "FORBIDDEN", "Not your asset.")
    key = asset.storage_key[: -len(".wav")] + ".json" if asset.storage_key.endswith(".wav") else None
    if key is None:
        raise ApiError(404, "WAVEFORM_NOT_FOUND", "No waveform for this asset.")
    try:
        stored = request.app.state.storage.get(key)
    except FileNotFoundError:
        try:
            wav = request.app.state.storage.get(asset.storage_key)
        except FileNotFoundError:
            raise ApiError(404, "WAVEFORM_NOT_FOUND", "Audio file is missing.")
        from ..peaks import peaks_json

        body = peaks_json(wav.body)
        try:
            request.app.state.storage.put(key, body)
        except OSError:
            pass
        return Response(content=body, media_type="application/json")
    return Response(content=stored.body, media_type="application/json")


@router.get("/artifacts/{asset_id}/manifest")
def artifact_manifest(
    asset_id: str,
    request: Request,
    owner_id: str = Depends(owner_from_request),
) -> JSONResponse:
    with request.app.state.db.session() as session:
        asset = session.execute(select(Asset).where(Asset.id == asset_id)).scalar_one_or_none()
        if asset is None or asset.owner_id != owner_id:
            raise ApiError(404, "ASSET_NOT_FOUND", "Asset not found.")
    return JSONResponse({"asset_id": asset.id, "manifest": asset.manifest_json or {}})


class ArtifactPatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    shared: bool | None = None


@router.patch("/artifacts/{asset_id}")
def artifact_patch(
    asset_id: str,
    payload: ArtifactPatch,
    request: Request,
    owner_id: str = Depends(owner_from_request),
) -> JSONResponse:
    with request.app.state.db.session() as session:
        asset = session.execute(select(Asset).where(Asset.id == asset_id)).scalar_one_or_none()
        if asset is None or asset.owner_id != owner_id:
            raise ApiError(404, "ASSET_NOT_FOUND", "Asset not found.")
        if payload.title is not None:
            asset.title = payload.title
        if payload.shared is not None:
            asset.shared = payload.shared
        session.commit()
        session.refresh(asset)
        return JSONResponse(
            {
                "asset_id": asset.id,
                "title": asset.title,
                "shared": asset.shared,
                "tags": list(asset.tags_json or []),
            }
        )


@router.post("/artifacts/{asset_id}/favorite")
def artifact_favorite(
    asset_id: str,
    request: Request,
    owner_id: str = Depends(owner_from_request),
) -> JSONResponse:
    from ..models import Favorite

    with request.app.state.db.session() as session:
        asset = session.execute(select(Asset).where(Asset.id == asset_id)).scalar_one_or_none()
        if asset is None or (asset.owner_id != owner_id and not asset.shared):
            raise ApiError(404, "ASSET_NOT_FOUND", "Asset not found.")
        existing = session.execute(
            select(Favorite).where(Favorite.owner_id == owner_id, Favorite.asset_id == asset_id)
        ).scalar_one_or_none()
        if existing is not None:
            session.delete(existing)
            session.commit()
            return JSONResponse({"asset_id": asset_id, "favorite": False})
        session.add(Favorite(owner_id=owner_id, asset_id=asset_id))
        session.commit()
        return JSONResponse({"asset_id": asset_id, "favorite": True})


@router.post("/artifacts/{asset_id}/play", status_code=202)
def artifact_play(asset_id: str, request: Request) -> JSONResponse:
    """Record a play; anonymous visitors are allowed."""
    from ..deps import owner_from_request
    from ..errors import ApiError as _ApiError
    from ..models import PlayEvent

    try:
        viewer = owner_from_request(request)
    except _ApiError:
        viewer = "anon"
    with request.app.state.db.session() as session:
        asset = session.execute(select(Asset).where(Asset.id == asset_id)).scalar_one_or_none()
        if asset is None or asset.deleted_at is not None:
            raise ApiError(404, "ASSET_NOT_FOUND", "Asset not found.")
        session.add(PlayEvent(asset_id=asset_id, viewer_id=viewer))
        session.commit()
    return JSONResponse({"asset_id": asset_id, "recorded": True}, status_code=202)


@router.get("/credits")
def credits_balance(
    request: Request,
    owner_id: str = Depends(owner_from_request),
) -> JSONResponse:
    from ..models import CreditEntry, User

    with request.app.state.db.session() as session:
        balance = None
        if owner_id.startswith("usr_"):
            user = session.get(User, owner_id[4:])
            if user is None:
                raise ApiError(401, "USER_NOT_FOUND", "Account not found for session owner.")
            balance = user.credits_balance
        entries = list(
            session.execute(
                select(CreditEntry)
                .where(CreditEntry.owner_id == owner_id)
                .order_by(CreditEntry.created_at.desc())
                .limit(20)
            ).scalars()
        )
    return JSONResponse(
        {
            "balance": balance,
            "entries": [
                {
                    "delta": e.delta,
                    "reason": e.reason,
                    "job_id": e.job_id,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in entries
            ],
        }
    )


def _creator_names(session, owner_ids: set[str]) -> dict[str, str]:
    from ..models import User

    user_ids = {o[4:] for o in owner_ids if o.startswith("usr_")}
    names: dict[str, str] = {}
    if user_ids:
        for u in session.execute(select(User).where(User.id.in_(user_ids))).scalars():
            names["usr_" + u.id] = u.username
    return names


def _like_counts(session, asset_ids: list[str]) -> dict[str, int]:
    from sqlalchemy import func as sa_func

    from ..models import Favorite

    if not asset_ids:
        return {}
    rows = session.execute(
        select(Favorite.asset_id, sa_func.count())
        .where(Favorite.asset_id.in_(asset_ids))
        .group_by(Favorite.asset_id)
    ).all()
    return {aid: int(n) for aid, n in rows}


@router.get("/loras")
def list_loras(request: Request) -> JSONResponse:
    """Public style-LoRA registry for the create widget's Style dropdown."""
    from ..models import Lora

    with request.app.state.db.session() as session:
        rows = list(
            session.execute(
                select(Lora).where(Lora.state == "active").order_by(Lora.kind, Lora.name)
            ).scalars()
        )
    return JSONResponse(
        {"loras": [{"id": l.id, "name": l.name, "kind": l.kind} for l in rows]}
    )


@router.get("/public/tracks")
def public_tracks(
    request: Request,
    limit: int = Query(default=12, ge=1, le=50),
    tag: str | None = Query(default=None, max_length=40),
    mode: str = Query(default="recent", pattern="^(recent|discover)$"),
) -> JSONResponse:
    settings = request.app.state.settings
    now = utcnow()
    from sqlalchemy import String as SAString
    from sqlalchemy import cast, func

    from ..deps import owner_from_request
    from ..errors import ApiError as _ApiError
    from ..models import PlayEvent

    try:
        viewer = owner_from_request(request)
    except _ApiError:
        viewer = None
    with request.app.state.db.session() as session:
        stmt = select(Asset).where(
            Asset.shared.is_(True),
            Asset.deleted_at.is_(None),
            Asset.mime.like("audio/%"),
            Asset.role == "mix_wav",
        )
        if tag:
            stmt = stmt.where(cast(Asset.tags_json, SAString).like(f'%"{tag.lower()}"%'))
        order = func.random() if mode == "discover" else Asset.created_at.desc()
        rows = list(session.execute(stmt.order_by(order).limit(limit)).scalars())
        likes = _like_counts(session, [a.id for a in rows])
        creators = _creator_names(session, {a.owner_id for a in rows})
        asset_ids = [a.id for a in rows]
        plays: dict[str, int] = {}
        favorites: set[str] = set()
        if asset_ids:
            from sqlalchemy import func as sa_func

            from ..models import Favorite

            for aid, n in session.execute(
                select(PlayEvent.asset_id, sa_func.count())
                .where(PlayEvent.asset_id.in_(asset_ids))
                .group_by(PlayEvent.asset_id)
            ).all():
                plays[aid] = int(n)
            if viewer:
                favorites = {
                    f.asset_id
                    for f in session.execute(
                        select(Favorite).where(Favorite.owner_id == viewer, Favorite.asset_id.in_(asset_ids))
                    ).scalars()
                }
    items = []
    for asset in rows:
        if asset.expires_at is not None and as_utc(asset.expires_at) <= now:
            continue
        expiry = now + timedelta(hours=24)
        token = make_token(settings.secret_key, asset.id, expiry)
        items.append(
            {
                "asset_id": asset.id,
                "title": asset.title,
                "duration_seconds": asset.duration_seconds,
                "created_at": asset.created_at.isoformat() if asset.created_at else None,
                "like_count": likes.get(asset.id, 0),
                "plays": plays.get(asset.id, 0),
                "favorite": asset.id in favorites,
                "tags": list(asset.tags_json or []),
                "creator": creators.get(asset.owner_id, "community"),
                "url": f"/api/v1/artifacts/{asset.id}/content?token={token}",
            }
        )
    return JSONResponse({"tracks": items})


@router.get("/tracks")
def my_tracks(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    owner_id: str = Depends(owner_from_request),
) -> JSONResponse:
    from ..models import Favorite

    settings = request.app.state.settings
    now = utcnow()
    with request.app.state.db.session() as session:
        rows = list(
            session.execute(
                select(Asset)
                .where(Asset.owner_id == owner_id, Asset.deleted_at.is_(None), Asset.mime.like("audio/%"))
                .order_by(Asset.created_at.desc())
                .limit(limit)
            ).scalars()
        )
        favorite_ids = set(
            session.execute(
                select(Favorite.asset_id).where(Favorite.owner_id == owner_id)
            ).scalars()
        )
        likes = _like_counts(session, [a.id for a in rows])
        job_ids = [a.job_id for a in rows if a.job_id]
        seeds: dict[str, int | None] = {}
        if job_ids:
            for jid, rjson in session.execute(
                select(Job.id, Job.request_json).where(Job.id.in_(job_ids))
            ).all():
                seeds[jid] = (rjson or {}).get("seed")
    items = []
    for asset in rows:
        expired = asset.expires_at is not None and as_utc(asset.expires_at) <= now
        expiry = now + timedelta(hours=24)
        token = make_token(settings.secret_key, asset.id, expiry)
        items.append(
            {
                "asset_id": asset.id,
                "role": asset.role,
                "title": asset.title,
                "shared": asset.shared,
                "favorite": asset.id in favorite_ids,
                "like_count": likes.get(asset.id, 0),
                "duration_seconds": asset.duration_seconds,
                "job_id": asset.job_id,
                "seed": seeds.get(asset.job_id),
                "created_at": asset.created_at.isoformat() if asset.created_at else None,
                "expired": expired,
                "url": f"/api/v1/artifacts/{asset.id}/content?token={token}",
            }
        )
    return JSONResponse({"tracks": items})
