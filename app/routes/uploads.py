"""Asset ingestion: upload sessions and asset reads (milestone 4).

Flow: allocate session -> PUT raw bytes to the data route -> complete runs
the probe (stdlib WAV reader, FFmpeg fallback) and finalizes an uploaded
asset. Non-audio bodies fail closed; nothing is silently accepted.
"""

from __future__ import annotations

import re
from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select

from ..audio_processing import AudioToolError, probe_audio
from ..deps import owner_from_request
from ..errors import ApiError
from ..models import Asset, UploadSession, new_uuid, utcnow
from ..schemas import AssetResponse, UploadCreate, UploadResponse

router = APIRouter(tags=["assets"])

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_MIME_BY_CODEC = {"pcm_s16le": "audio/wav", "pcm_s24le": "audio/wav", "mp3": "audio/mpeg", "flac": "audio/flac", "ogg": "audio/ogg"}


def _safe_filename(filename: str) -> str:
    name = _SAFE_NAME.sub("_", filename.split("/")[-1].split("\\")[-1]).strip("._") or "upload"
    return name[:100]


def _upload_response(session_obj: UploadSession) -> UploadResponse:
    return UploadResponse(
        upload_id=session_obj.id,
        status=session_obj.status,
        data_url=f"/api/v1/assets/uploads/{session_obj.id}/data",
        expires_at=session_obj.expires_at,
        bytes=session_obj.bytes,
        sha256=session_obj.sha256,
        asset_id=session_obj.asset_id,
        error=session_obj.error,
    )


def _asset_response(asset: Asset) -> AssetResponse:
    return AssetResponse(
        asset_id=asset.id,
        job_id=asset.job_id,
        role=asset.role,
        kind=asset.kind,
        source_asset_id=asset.source_asset_id,
        stem_source=asset.stem_source,
        stem_category=asset.stem_category,
        processing=asset.processing,
        mime=asset.mime,
        bytes=asset.bytes,
        sha256=asset.sha256,
        sample_rate=asset.sample_rate,
        channels=asset.channels,
        duration_seconds=asset.duration_seconds,
        synthetic=asset.synthetic,
        created_at=asset.created_at,
        expires_at=asset.expires_at,
        deleted=asset.deleted_at is not None,
    )


def _get_owned_upload(request: Request, upload_id: str, owner_id: str) -> UploadSession:
    with request.app.state.db.session() as session:
        upload = session.get(UploadSession, upload_id)
        if upload is None or upload.owner_id != owner_id:
            raise ApiError(404, "UPLOAD_NOT_FOUND", "Upload session not found.")
        session.expunge(upload)
        return upload


@router.post("/assets/uploads", status_code=201, response_model=UploadResponse)
def create_upload(
    payload: UploadCreate,
    request: Request,
    owner_id: str = Depends(owner_from_request),
) -> UploadResponse:
    settings = request.app.state.settings
    with request.app.state.db.session() as session:
        upload = UploadSession(
            id=new_uuid(),
            owner_id=owner_id,
            filename=_safe_filename(payload.filename),
            content_type=payload.content_type,
            status="awaiting_data",
            expires_at=utcnow() + timedelta(minutes=settings.upload_session_ttl_minutes),
        )
        session.add(upload)
        session.commit()
        return _upload_response(upload)


@router.put("/assets/uploads/{upload_id}/data")
async def put_upload_data(
    upload_id: str,
    request: Request,
    owner_id: str = Depends(owner_from_request),
) -> JSONResponse:
    settings = request.app.state.settings
    upload = _get_owned_upload(request, upload_id, owner_id)
    if upload.status not in ("awaiting_data", "data_received"):
        raise ApiError(409, "STATE_CONFLICT", f"Upload in state '{upload.status}' cannot receive data.")
    body = await request.body()
    if not body:
        raise ApiError(422, "UPLOAD_EMPTY", "Upload body is empty.")
    if len(body) > settings.max_upload_bytes:
        raise ApiError(413, "BODY_TOO_LARGE", "Upload exceeds the configured limit.", {"max_upload_bytes": settings.max_upload_bytes})
    key = f"uploads/{owner_id}/{upload.id}/{upload.filename}"
    checksum = request.app.state.storage.put(key, body)
    with request.app.state.db.session() as session:
        stored = session.get(UploadSession, upload_id)
        stored.storage_key = key
        stored.bytes = len(body)
        stored.sha256 = checksum
        stored.status = "data_received"
        session.commit()
        session.expunge(stored)
    return JSONResponse(status_code=200, content=_upload_response(stored).model_dump(mode="json"))


@router.post("/assets/uploads/{upload_id}/complete", status_code=201)
def complete_upload(
    upload_id: str,
    request: Request,
    owner_id: str = Depends(owner_from_request),
) -> JSONResponse:
    settings = request.app.state.settings
    upload = _get_owned_upload(request, upload_id, owner_id)
    if upload.status == "completed" and upload.asset_id:
        with request.app.state.db.session() as session:
            existing = session.get(Asset, upload.asset_id)
            return JSONResponse(status_code=200, content={"asset": _asset_response(existing).model_dump(mode="json")})
    if upload.status != "data_received":
        raise ApiError(409, "STATE_CONFLICT", f"Upload in state '{upload.status}' cannot be completed.")
    body = request.app.state.storage.get(upload.storage_key).body
    try:
        probe = probe_audio(body, settings.ffprobe_bin)
    except AudioToolError:
        with request.app.state.db.session() as session:
            stored = session.get(UploadSession, upload_id)
            stored.status = "failed"
            stored.error = "UPLOAD_NOT_AUDIO"
            session.commit()
        raise ApiError(422, "UPLOAD_NOT_AUDIO", "Uploaded bytes are not decodable audio.")
    mime = _MIME_BY_CODEC.get(probe.codec, upload.content_type or "application/octet-stream")
    with request.app.state.db.session() as session:
        asset = Asset(
            id=new_uuid(),
            job_id=None,
            owner_id=owner_id,
            attempt_id=None,
            storage_key=upload.storage_key,
            role="source_upload",
            kind="uploaded",
            mime=mime,
            bytes=upload.bytes or len(body),
            sha256=upload.sha256 or "",
            sample_rate=probe.sample_rate,
            channels=probe.channels,
            duration_seconds=round(probe.duration_seconds, 3) if probe.duration_seconds else None,
            synthetic=False,
            finalized_at=utcnow(),
            expires_at=None,
        )
        session.add(asset)
        stored = session.get(UploadSession, upload_id)
        stored.status = "completed"
        stored.asset_id = asset.id
        session.commit()
        return JSONResponse(status_code=201, content={"asset": _asset_response(asset).model_dump(mode="json")})


@router.get("/assets/{asset_id}", response_model=AssetResponse)
def get_asset(
    asset_id: str,
    request: Request,
    owner_id: str = Depends(owner_from_request),
) -> AssetResponse:
    with request.app.state.db.session() as session:
        asset = session.get(Asset, asset_id)
        if asset is None or asset.owner_id != owner_id:
            raise ApiError(404, "ASSET_NOT_FOUND", "Asset not found.")
        if asset.deleted_at is not None:
            raise ApiError(410, "ASSET_DELETED", "Asset has been revoked.")
        return _asset_response(asset)


@router.delete("/assets/{asset_id}", status_code=204)
def delete_asset(
    asset_id: str,
    request: Request,
    owner_id: str = Depends(owner_from_request),
) -> Response:
    with request.app.state.db.session() as session:
        asset = session.get(Asset, asset_id)
        if asset is None or asset.owner_id != owner_id:
            raise ApiError(404, "ASSET_NOT_FOUND", "Asset not found.")
        asset.deleted_at = utcnow()
        session.commit()
    return Response(status_code=204)
