"""Export admission: POST /exports queues an audio.export job (milestone 4).

Unsupported export settings are rejected before queuing; requested outputs
are never silently dropped. The CPU audio worker performs the work.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from ..audio_worker import EXPORT_MODEL_ID, EXPORT_RECIPE_REVISION, MP3_BITRATES
from ..deps import owner_from_request
from ..errors import ApiError
from ..models import Job, ProjectVersion, new_uuid, utcnow
from ..orchestration import append_event, enqueue
from ..routes.jobs import _idempotency_key
from ..schemas import ExportRequest, JobAcceptedResponse

router = APIRouter(tags=["exports"])

EXPORT_ROUTE = "POST /exports"


@router.post("/exports", status_code=202, response_model=JobAcceptedResponse)
def create_export(
    payload: ExportRequest,
    request: Request,
    owner_id: str = Depends(owner_from_request),
) -> JSONResponse:
    settings = request.app.state.settings
    outputs = sorted(set(payload.outputs))
    if not outputs:
        raise ApiError(422, "EXPORT_OUTPUTS_REQUIRED", "At least one output must be requested.")
    if payload.wav is not None:
        if payload.wav.sample_rate != "native":
            raise ApiError(
                422,
                "EXPORT_SETTING_UNSUPPORTED",
                "Only native sample rate export is implemented; the original stays intact.",
                {"requested_sample_rate": payload.wav.sample_rate},
            )
        if payload.wav.encoding != "pcm16":
            raise ApiError(
                422,
                "EXPORT_SETTING_UNSUPPORTED",
                "Only pcm16 WAV export is implemented.",
                {"requested_encoding": payload.wav.encoding},
            )
    if payload.mp3 is not None and payload.mp3.bitrate_kbps not in MP3_BITRATES:
        raise ApiError(
            422,
            "EXPORT_SETTING_UNSUPPORTED",
            "Unsupported MP3 bitrate.",
            {"supported_bitrates_kbps": list(MP3_BITRATES)},
        )
    key = _idempotency_key(request, settings.max_idempotency_key_length)

    with request.app.state.db.session() as session:
        version = session.get(ProjectVersion, payload.source_version_id)
        if version is None or version.owner_id != owner_id:
            raise ApiError(404, "VERSION_NOT_FOUND", "Source version not found.")
        if version.source_asset_id is None:
            raise ApiError(422, "VERSION_HAS_NO_AUDIO", "Source version has no audio asset.")

        from sqlalchemy import select

        from ..models import IdempotencyRecord

        existing = session.execute(
            select(IdempotencyRecord).where(
                IdempotencyRecord.owner_id == owner_id,
                IdempotencyRecord.route == EXPORT_ROUTE,
                IdempotencyRecord.key == key,
            )
        ).scalar_one_or_none()
        request_hash = payload.request_hash()
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ApiError(
                    409,
                    "IDEMPOTENCY_CONFLICT",
                    "Idempotency-Key was already used with a different request.",
                    {"job_id": existing.job_id},
                )
            job = session.execute(select(Job).where(Job.id == existing.job_id)).scalar_one()
        else:
            job = Job(
                id=new_uuid(),
                owner_id=owner_id,
                operation="audio.export",
                model_id=EXPORT_MODEL_ID,
                model_revision=EXPORT_RECIPE_REVISION,
                status="queued",
                request_json=payload.model_dump(mode="json"),
                request_hash=request_hash,
                idempotency_key=key,
            )
            session.add(job)
            session.add(
                IdempotencyRecord(
                    owner_id=owner_id,
                    route=EXPORT_ROUTE,
                    key=key,
                    request_hash=request_hash,
                    job_id=job.id,
                    expires_at=utcnow() + timedelta(hours=settings.idempotency_retention_hours),
                )
            )
            enqueue(session, job, settings)
            append_event(session, job.id, "queued", "queued")
            session.commit()

    status_url = f"/api/v1/jobs/{job.id}"
    body = JobAcceptedResponse(
        job_id=job.id,
        status=job.status,
        model_id=job.model_id,
        model_revision=job.model_revision,
        status_url=status_url,
        events_url=f"{status_url}/events",
        poll_after_seconds=settings.poll_after_seconds,
        required_notices=[],
    )
    return JSONResponse(status_code=202, content=body.model_dump(mode="json"), headers={"Location": status_url})
