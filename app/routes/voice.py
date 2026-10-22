"""UAIS artist voice endpoints: dataset, analysis, training, validation, resolver.

One training library per artist; recordings are QC'd on upload and preserved
byte-for-byte. Finalizing freezes an immutable dataset version and marks
adapters built from older versions stale. Training/validation are queue jobs;
durable records are authoritative.
"""

from __future__ import annotations

import hashlib
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..deps import owner_from_request
from ..errors import ApiError
from ..models import (
    Asset,
    ArtistProfile,
    CreditEntry,
    User,
    VoiceAdapter,
    VoiceAnalysis,
    VoiceDataset,
    VoiceDatasetVersion,
    VoiceProfile,
    VoiceRecording,
    new_uuid,
    utcnow,
)
from ..orchestration import append_event, enqueue
from ..routes.artist import _accepted, _create_job, _get_owned_profile
from ..routes.jobs import _idempotency_key
from ..schemas import StrictModel
from ..uais.capabilities import capability
from ..uais.qc import QcError, inspect_bytes
from ..uais.resolver import compatibility_matrix, resolve_plan

router = APIRouter(tags=["voice"])

VOICE_OPERATIONS = ("voice.analyze", "voice.train", "voice.validate")
SUPPORTED_UPLOAD_EXT = (".wav", ".flac", ".mp3")


class VoiceTrainRequest(StrictModel):
    model_selection: str = "ace-step-1.5-turbo"
    hyperparams: dict[str, Any] = Field(default_factory=dict)
    seed: int | None = Field(default=None, ge=0, le=2**31 - 1)
    max_epochs: int | None = Field(default=None, ge=1, le=2000)

    def request_hash(self) -> str:
        import json

        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class VoiceValidateRequest(StrictModel):
    adapter_id: str

    def request_hash(self) -> str:
        return hashlib.sha256(self.adapter_id.encode("utf-8")).hexdigest()


class VoiceProfilePatch(StrictModel):
    description: dict[str, Any] | None = None
    performance: dict[str, Any] | None = None
    notes: str | None = Field(default=None, max_length=500)


def _get_dataset(session, profile_id: str, owner_id: str, create: bool = False) -> VoiceDataset | None:
    from sqlalchemy import select

    dataset = session.execute(
        select(VoiceDataset).where(VoiceDataset.artist_profile_id == profile_id)
    ).scalars().first()
    if dataset is None:
        if not create:
            return None
        dataset = VoiceDataset(id=new_uuid(), artist_profile_id=profile_id, owner_id=owner_id)
        session.add(dataset)
        session.flush()
    return dataset


def _recording_json(r: VoiceRecording) -> dict:
    return {
        "recording_id": r.id,
        "asset_id": r.asset_id,
        "filename": r.filename,
        "sha256": r.sha256,
        "bytes": r.bytes,
        "duration_seconds": r.duration_seconds,
        "sample_rate": r.sample_rate,
        "channels": r.channels,
        "qc": r.qc_json,
        "lyrics_chars": len(r.lyrics_text or ""), "lyrics_sha256": r.lyrics_sha256,
        "consent": r.consent_json,
        "vocal_asset_id": r.vocal_asset_id,
        "state": r.state,
        "added_at": r.added_at.isoformat() if r.added_at else None,
    }


def _adapter_json(a: VoiceAdapter) -> dict:
    return {
        "adapter_id": a.id,
        "artist_id": a.artist_profile_id,
        "voice_profile_id": a.voice_profile_id,
        "dataset_version_id": a.dataset_version_id,
        "model_selection": a.model_selection,
        "engine_model": a.engine_model,
        "base_revision": a.base_revision,
        "adapter_format": a.adapter_format,
        "architecture": a.architecture_json,
        "training_job_id": a.training_job_id,
        "storage_prefix": a.storage_prefix,
        "files": a.files_json,
        "adapter_sha256": a.adapter_sha256,
        "state": a.state,
        "metrics": a.metrics_json,
        "validation": a.validation_json,
        "last_validated_at": a.last_validated_at.isoformat() if a.last_validated_at else None,
        "limitations": a.limitations_json,
        "error_code": a.error_code,
        "error_message": a.error_message,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


def _profile_json(p: VoiceProfile) -> dict:
    return {
        "voice_profile_id": p.id,
        "artist_id": p.artist_profile_id,
        "version_number": p.version_number,
        "status": p.status,
        "dataset_version_id": p.dataset_version_id,
        "identity": p.identity_json,
        "description": p.description_json,
        "performance": p.performance_json,
        "analysis_model": p.analysis_model,
        "embedding_summary": {
            "model": (p.embeddings_json or {}).get("model"),
            "input_type": (p.embeddings_json or {}).get("input_type"),
            "recordings": len((p.embeddings_json or {}).get("recordings", {})),
            "has_centroid": bool((p.embeddings_json or {}).get("centroid")),
        },
        "notes": p.notes,
        "is_default": p.is_default,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def _charge_credits(session, owner_id: str, cost: int, reason: str, job_id: str, external_id: str) -> None:
    if cost <= 0 or not owner_id.startswith("usr_"):
        return
    user = session.get(User, owner_id[4:])
    if user is None:
        raise ApiError(401, "USER_NOT_FOUND", "Account not found for session owner.")
    if user.credits_balance < cost:
        raise ApiError(402, "INSUFFICIENT_CREDITS", "Not enough credits for this voice operation.",
                       {"cost": cost, "balance": user.credits_balance})
    user.credits_balance -= cost
    session.add(CreditEntry(owner_id=owner_id, delta=-cost, reason=reason, job_id=job_id,
                            external_id=external_id))


# --- dataset ------------------------------------------------------------------


@router.post("/artist-profiles/{profile_id}/voice/dataset", status_code=201)
def create_voice_dataset(profile_id: str, request: Request,
                         owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    with request.app.state.db.session() as session:
        _get_owned_profile(session, profile_id, owner_id)
        dataset = _get_dataset(session, profile_id, owner_id, create=True)
        session.commit()
        body = {"dataset_id": dataset.id, "artist_id": profile_id, "name": dataset.name,
                "latest_version_number": dataset.latest_version_number,
                "created_at": dataset.created_at.isoformat()}
    return JSONResponse(status_code=201, content=body)


@router.get("/artist-profiles/{profile_id}/voice/dataset")
def get_voice_dataset(profile_id: str, request: Request,
                      owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    from sqlalchemy import select

    with request.app.state.db.session() as session:
        _get_owned_profile(session, profile_id, owner_id)
        dataset = _get_dataset(session, profile_id, owner_id)
        if dataset is None:
            raise ApiError(404, "VOICE_DATASET_NOT_FOUND", "Artist has no training library yet.")
        recordings = list(session.execute(
            select(VoiceRecording)
            .where(VoiceRecording.dataset_id == dataset.id, VoiceRecording.state == "active")
            .order_by(VoiceRecording.added_at)
        ).scalars())
        version = session.execute(
            select(VoiceDatasetVersion)
            .where(VoiceDatasetVersion.dataset_id == dataset.id)
            .order_by(VoiceDatasetVersion.version_number.desc())
        ).scalars().first()
        body = {
            "dataset_id": dataset.id,
            "artist_id": profile_id,
            "name": dataset.name,
            "latest_version_number": dataset.latest_version_number,
            "recordings": [_recording_json(r) for r in recordings],
            "latest_version": {
                "dataset_version_id": version.id,
                "version_number": version.version_number,
                "frozen_sha256": version.frozen_sha256,
                "report": version.report_json,
                "created_at": version.created_at.isoformat(),
            } if version else None,
        }
    return JSONResponse(content=body)


@router.post("/artist-profiles/{profile_id}/voice/dataset/recordings", status_code=201)
async def add_recording(profile_id: str, request: Request,
                        owner_id: str = Depends(owner_from_request),
                        file: UploadFile = File(...),
                        consent: str = Form(default="", max_length=500),
                        caption: str = Form(default="", max_length=300),
                        lyrics: str = Form(default="")) -> JSONResponse:
    settings = request.app.state.settings
    filename = file.filename or "recording"
    if not filename.lower().endswith(SUPPORTED_UPLOAD_EXT):
        raise ApiError(422, "FORMAT_UNSUPPORTED",
                       "Training recordings must be WAV, FLAC or MP3.",
                       {"supported": list(SUPPORTED_UPLOAD_EXT)})
    body = await file.read()
    if not body:
        raise ApiError(422, "EMPTY_FILE", "Recording file is empty.")
    if len(body) > settings.voice_max_upload_bytes:
        raise ApiError(413, "FILE_TOO_LARGE", "Recording exceeds the upload size limit.",
                       {"max_bytes": settings.voice_max_upload_bytes})
    try:
        qc = inspect_bytes(body, settings.ffmpeg_bin, settings.ffprobe_bin,
                           settings.voice_max_recording_seconds)
    except QcError as exc:
        raise ApiError(422, exc.code, exc.message) from exc
    if qc["verdict"] == "rejected":
        raise ApiError(422, "QC_REJECTED", "Recording is not usable for training.",
                       {"reasons": qc["reasons"], "checks": qc["checks"]})

    from sqlalchemy import select

    with request.app.state.db.session() as session:
        _get_owned_profile(session, profile_id, owner_id)
        dataset = _get_dataset(session, profile_id, owner_id, create=True)
        sha256 = hashlib.sha256(body).hexdigest()
        duplicate = session.execute(
            select(VoiceRecording).where(
                VoiceRecording.dataset_id == dataset.id,
                VoiceRecording.sha256 == sha256,
                VoiceRecording.state == "active",
            )
        ).scalars().first()
        if duplicate is not None:
            raise ApiError(409, "RECORDING_DUPLICATE", "This exact recording is already in the library.",
                           {"recording_id": duplicate.id})
        key = f"owners/{owner_id}/voice/{dataset.id}/{new_uuid()}{filename[filename.rfind('.'):].lower()}"
        stored = request.app.state.storage.put(key, body)
        mime = {".wav": "audio/wav", ".flac": "audio/flac", ".mp3": "audio/mpeg"}.get(
            filename[filename.rfind('.'):].lower(), "application/octet-stream")
        asset = Asset(
            id=new_uuid(), owner_id=owner_id, storage_key=key, role="training_source",
            kind="uploaded", mime=mime, bytes=len(body), sha256=stored,
            title=filename, sample_rate=qc["probe"].get("sample_rate"),
            channels=qc["probe"].get("channels"),
            duration_seconds=qc["probe"].get("duration_seconds"), finalized_at=utcnow(),
        )
        session.add(asset)
        session.flush()
        recording = VoiceRecording(
            id=new_uuid(), dataset_id=dataset.id, artist_profile_id=profile_id, owner_id=owner_id,
            asset_id=asset.id, filename=filename, sha256=sha256, bytes=len(body),
            duration_seconds=qc["checks"].get("decoded_duration_seconds"),
            sample_rate=qc["probe"].get("sample_rate"), channels=qc["probe"].get("channels"),
            qc_json=qc,
            consent_json={"declaration": consent or "owner-authorized for voice training",
                          "declared_at": utcnow().isoformat()},
            separation_json={},
        )
        if caption.strip():
            recording.qc_json = {**qc, "caption": caption.strip()}
        if lyrics:
            # Submitted lyrics are immutable: stored exactly as sent (invariant 1).
            recording.lyrics_text = lyrics
            recording.lyrics_sha256 = hashlib.sha256(lyrics.encode("utf-8")).hexdigest()
        session.add(recording)
        session.commit()
        out = _recording_json(recording)
        out["asset_id"] = asset.id
    return JSONResponse(status_code=201, content=out)


@router.delete("/artist-profiles/{profile_id}/voice/dataset/recordings/{recording_id}", status_code=204)
def remove_recording(profile_id: str, recording_id: str, request: Request,
                     owner_id: str = Depends(owner_from_request)):
    from fastapi import Response

    with request.app.state.db.session() as session:
        _get_owned_profile(session, profile_id, owner_id)
        recording = session.get(VoiceRecording, recording_id)
        if recording is None or recording.artist_profile_id != profile_id or recording.state != "active":
            raise ApiError(404, "RECORDING_NOT_FOUND", "Active recording not found.")
        recording.state = "removed"
        recording.removed_at = utcnow()
        session.commit()
    return Response(status_code=204)


@router.post("/artist-profiles/{profile_id}/voice/dataset/finalize", status_code=201)
def finalize_voice_dataset(profile_id: str, request: Request,
                           owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    from sqlalchemy import select

    with request.app.state.db.session() as session:
        _get_owned_profile(session, profile_id, owner_id)
        dataset = _get_dataset(session, profile_id, owner_id)
        if dataset is None:
            raise ApiError(404, "VOICE_DATASET_NOT_FOUND", "Artist has no training library yet.")
        recordings = list(session.execute(
            select(VoiceRecording)
            .where(VoiceRecording.dataset_id == dataset.id, VoiceRecording.state == "active")
            .order_by(VoiceRecording.added_at, VoiceRecording.id)
        ).scalars())
        usable = [r for r in recordings if (r.qc_json or {}).get("verdict") != "rejected"]
        if not usable:
            raise ApiError(422, "DATASET_EMPTY", "Finalize requires at least one usable recording.")
        manifest = [{"recording_id": r.id, "asset_id": r.asset_id, "sha256": r.sha256,
                     "duration_seconds": r.duration_seconds,
                     "caption": (r.qc_json or {}).get("caption"),
                     "lyrics": r.lyrics_text, "lyrics_sha256": r.lyrics_sha256}
                    for r in usable]
        frozen = hashlib.sha256(
            "\n".join(f"{m['sha256']}|{m['recording_id']}" for m in sorted(manifest, key=lambda m: m["recording_id"])).encode()
        ).hexdigest()
        usable_seconds = round(sum(r.duration_seconds or 0.0 for r in usable), 3)
        flagged = [r.id for r in usable if (r.qc_json or {}).get("verdict") == "flagged"]
        warnings = []
        if usable_seconds < 60:
            warnings.append("under one minute of usable audio: identity may be unstable (threshold is configurable, not universal)")
        if flagged:
            warnings.append(f"{len(flagged)} recording(s) flagged by QC")
        version = VoiceDatasetVersion(
            id=new_uuid(), dataset_id=dataset.id, owner_id=owner_id,
            version_number=dataset.latest_version_number + 1, frozen_sha256=frozen,
            manifest_json={"recordings": manifest},
            report_json={"recordings": len(usable), "usable_duration_seconds": usable_seconds,
                         "flagged_recordings": flagged, "warnings": warnings},
        )
        session.add(version)
        dataset.latest_version_number = version.version_number
        stale = 0
        for adapter in session.execute(
            select(VoiceAdapter).where(
                VoiceAdapter.artist_profile_id == profile_id,
                VoiceAdapter.state.in_(("validated", "ready")),
            )
        ).scalars():
            if adapter.dataset_version_id != version.id:
                adapter.state = "stale"
                stale += 1
        session.commit()
        body = {"dataset_version_id": version.id, "version_number": version.version_number,
                "frozen_sha256": frozen, "report": version.report_json,
                "adapters_marked_stale": stale,
                "created_at": version.created_at.isoformat()}
    return JSONResponse(status_code=201, content=body)


# --- jobs ---------------------------------------------------------------------


@router.post("/artist-profiles/{profile_id}/voice/analyze", status_code=202)
def analyze_voice(profile_id: str, request: Request,
                  owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    settings = request.app.state.settings
    with request.app.state.db.session() as session:
        _get_owned_profile(session, profile_id, owner_id)
        dataset = _get_dataset(session, profile_id, owner_id)
        if dataset is None or dataset.latest_version_number == 0:
            raise ApiError(409, "STATE_CONFLICT", "Finalize a dataset version before analysis.")
        request_hash = hashlib.sha256(f"analyze:{dataset.latest_version_number}".encode()).hexdigest()
        job, created = _create_job(session, request, owner_id, "POST voice/analyze", "voice.analyze",
                                   settings.train_queue_model_id, settings.voice_embedding_model,
                                   {"profile_id": profile_id}, request_hash)
        session.commit()
    return _accepted(job, request)


@router.post("/artist-profiles/{profile_id}/voice/train", status_code=202)
def train_voice(profile_id: str, payload: VoiceTrainRequest, request: Request,
                owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    settings = request.app.state.settings
    cap = capability(payload.model_selection)
    if cap is None:
        raise ApiError(422, "MODEL_VOICE_UNSUPPORTED",
                       "This generation model has no registered voice capability manifest.",
                       {"model_selection": payload.model_selection})
    if cap.training_recipe is None:
        raise ApiError(422, "TRAINING_UNSUPPORTED",
                       "No verified training recipe exists for this model.",
                       {"model_selection": payload.model_selection})
    key = _idempotency_key(request, settings.max_idempotency_key_length)
    from sqlalchemy import select

    with request.app.state.db.session() as session:
        _get_owned_profile(session, profile_id, owner_id)
        dataset = _get_dataset(session, profile_id, owner_id)
        if dataset is None or dataset.latest_version_number == 0:
            raise ApiError(409, "STATE_CONFLICT", "Finalize a dataset version before training.")
        version = session.execute(
            select(VoiceDatasetVersion)
            .where(VoiceDatasetVersion.dataset_id == dataset.id,
                   VoiceDatasetVersion.version_number == dataset.latest_version_number)
        ).scalars().first()
        profile = session.execute(
            select(VoiceProfile)
            .where(VoiceProfile.artist_profile_id == profile_id)
            .order_by(VoiceProfile.version_number.desc())
        ).scalars().first()
        running = session.execute(
            select(VoiceAdapter).where(
                VoiceAdapter.artist_profile_id == profile_id,
                VoiceAdapter.model_selection == payload.model_selection,
                VoiceAdapter.state == "training",
            )
        ).scalars().first()
        if running is not None:
            raise ApiError(409, "TRAINING_IN_PROGRESS",
                           "An adapter for this model is already training for this artist.",
                           {"adapter_id": running.id})
        request_hash = hashlib.sha256(
            f"{payload.request_hash()}:{version.frozen_sha256}".encode()).hexdigest()
        queue_model_id = (settings.train_queue_model_id if cap.param_class != "4b"
                          else settings.train_xl_queue_model_id)
        job, created = _create_job(
            session, request, owner_id, "POST voice/train", "voice.train",
            queue_model_id, cap.training_recipe,
            {"profile_id": profile_id, "model_selection": payload.model_selection,
             "hyperparams": payload.hyperparams, "seed": payload.seed,
             "max_epochs": payload.max_epochs},
            request_hash,
        )
        adapter = None
        if created:
            adapter = VoiceAdapter(
                id=new_uuid(), artist_profile_id=profile_id, owner_id=owner_id,
                voice_profile_id=profile.id if profile else None,
                dataset_version_id=version.id, model_selection=payload.model_selection,
                engine_model=cap.engine_model, base_revision=cap.base_revision,
                adapter_format=cap.adapter_format,
                architecture_json={"recipe": cap.training_recipe,
                                   "adapter_load_verified": cap.adapter_load_verified},
                training_config_json={"hyperparams": payload.hyperparams, "seed": payload.seed,
                                      "max_epochs": payload.max_epochs},
                training_job_id=job.id,
            )
            session.add(adapter)
            job.request_json = {**job.request_json, "adapter_id": adapter.id}
            _charge_credits(session, owner_id, settings.credit_cost_training, "training",
                            job.id, f"voice-train:{job.id}")
        session.commit()
        adapter_id = adapter.id if adapter else None
    return JSONResponse(
        status_code=202,
        content={**_accepted_body(job, request), "adapter_id": adapter_id},
    )


def _accepted_body(job, request: Request) -> dict:
    settings = request.app.state.settings
    return {
        "job_id": job.id, "status": job.status, "model_id": job.model_id,
        "model_revision": job.model_revision, "status_url": f"/api/v1/jobs/{job.id}",
        "events_url": f"/api/v1/jobs/{job.id}/events",
        "poll_after_seconds": settings.poll_after_seconds, "required_notices": [],
    }


@router.post("/artist-profiles/{profile_id}/voice/validate", status_code=202)
def validate_voice(profile_id: str, payload: VoiceValidateRequest, request: Request,
                   owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    settings = request.app.state.settings
    with request.app.state.db.session() as session:
        _get_owned_profile(session, profile_id, owner_id)
        adapter = session.get(VoiceAdapter, payload.adapter_id)
        if adapter is None or adapter.artist_profile_id != profile_id:
            raise ApiError(404, "ADAPTER_NOT_FOUND", "Adapter not found for this artist.")
        if adapter.state not in ("ready", "stale", "validated"):
            raise ApiError(409, "STATE_CONFLICT",
                           "Only trained adapters can be validated.", {"state": adapter.state})
        job, created = _create_job(session, request, owner_id, "POST voice/validate", "voice.validate",
                                   settings.train_queue_model_id, adapter.base_revision,
                                   {"profile_id": profile_id, "adapter_id": adapter.id},
                                   payload.request_hash())
        if created:
            _charge_credits(session, owner_id, settings.credit_cost_validation, "validation",
                            job.id, f"voice-validate:{job.id}")
        session.commit()
    return _accepted(job, request)


# --- status / registry / resolver ----------------------------------------------


@router.get("/artist-profiles/{profile_id}/voice/status")
def voice_status(profile_id: str, request: Request,
                 owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    from sqlalchemy import select

    from ..models import Job

    with request.app.state.db.session() as session:
        _get_owned_profile(session, profile_id, owner_id)
        dataset = _get_dataset(session, profile_id, owner_id)
        adapters = list(session.execute(
            select(VoiceAdapter).where(VoiceAdapter.artist_profile_id == profile_id)
            .order_by(VoiceAdapter.created_at.desc())
        ).scalars())
        profiles = list(session.execute(
            select(VoiceProfile).where(VoiceProfile.artist_profile_id == profile_id)
            .order_by(VoiceProfile.version_number.desc())
        ).scalars())
        jobs = list(session.execute(
            select(Job).where(Job.owner_id == owner_id, Job.operation.in_(VOICE_OPERATIONS))
            .order_by(Job.seq.desc()).limit(10)
        ).scalars())
        analyses = list(session.execute(
            select(VoiceAnalysis).where(VoiceAnalysis.artist_profile_id == profile_id)
            .order_by(VoiceAnalysis.created_at.desc()).limit(5)
        ).scalars())
    return JSONResponse(content={
        "dataset": None if dataset is None else {
            "dataset_id": dataset.id, "latest_version_number": dataset.latest_version_number},
        "voice_profiles": [_profile_json(p) for p in profiles],
        "adapters": [_adapter_json(a) for a in adapters],
        "analyses": [{"analysis_id": a.id, "embedding_model": a.embedding_model,
                      "input_type": a.input_type, "created_at": a.created_at.isoformat()}
                     for a in analyses],
        "recent_jobs": [{"job_id": j.id, "operation": j.operation, "status": j.status,
                         "stage": j.stage, "progress": j.progress} for j in jobs],
    })


@router.get("/artist-profiles/{profile_id}/voice/compatibility")
def voice_compatibility(profile_id: str, request: Request,
                        owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    with request.app.state.db.session() as session:
        _get_owned_profile(session, profile_id, owner_id)
        matrix = compatibility_matrix(session, owner_id, profile_id)
    return JSONResponse(content={"artist_id": profile_id, "models": matrix})


@router.get("/artist-profiles/{profile_id}/voice/compatibility/{model_selection}")
def voice_compatibility_one(profile_id: str, model_selection: str, request: Request,
                            owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    from ..uais.resolver import compatibility

    with request.app.state.db.session() as session:
        _get_owned_profile(session, profile_id, owner_id)
        plan = resolve_plan(session, owner_id, profile_id, model_selection, "best")
        compat = compatibility(session, owner_id, profile_id, model_selection)
    return JSONResponse(content={"compatibility": compat, "plan": plan})


@router.get("/artist-profiles/{profile_id}/voice/adapters")
def list_adapters(profile_id: str, request: Request,
                  owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    from sqlalchemy import select

    with request.app.state.db.session() as session:
        _get_owned_profile(session, profile_id, owner_id)
        adapters = list(session.execute(
            select(VoiceAdapter).where(VoiceAdapter.artist_profile_id == profile_id)
            .order_by(VoiceAdapter.created_at.desc())
        ).scalars())
    return JSONResponse(content=[_adapter_json(a) for a in adapters])


@router.get("/artist-profiles/{profile_id}/voice/adapters/capabilities")
def adapter_capabilities(profile_id: str, request: Request,
                         owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    from ..uais.capabilities import VOICE_CAPABILITIES

    with request.app.state.db.session() as session:
        _get_owned_profile(session, profile_id, owner_id)
    return JSONResponse(content={k: c.manifest() for k, c in VOICE_CAPABILITIES.items()})


# --- voice profiles -------------------------------------------------------------


@router.get("/artist-profiles/{profile_id}/voice/profiles")
def list_voice_profiles(profile_id: str, request: Request,
                        owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    from sqlalchemy import select

    with request.app.state.db.session() as session:
        _get_owned_profile(session, profile_id, owner_id)
        profiles = list(session.execute(
            select(VoiceProfile).where(VoiceProfile.artist_profile_id == profile_id)
            .order_by(VoiceProfile.version_number.desc())
        ).scalars())
    return JSONResponse(content=[_profile_json(p) for p in profiles])


@router.patch("/artist-profiles/{profile_id}/voice/profiles/{voice_profile_id}")
def patch_voice_profile(profile_id: str, voice_profile_id: str, payload: VoiceProfilePatch,
                        request: Request,
                        owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    with request.app.state.db.session() as session:
        _get_owned_profile(session, profile_id, owner_id)
        profile = session.get(VoiceProfile, voice_profile_id)
        if profile is None or profile.artist_profile_id != profile_id:
            raise ApiError(404, "VOICE_PROFILE_NOT_FOUND", "Voice profile not found.")
        if payload.description is not None:
            profile.description_json = payload.description
        if payload.performance is not None:
            profile.performance_json = payload.performance
        if payload.notes is not None:
            profile.notes = payload.notes
        session.commit()
        body = _profile_json(profile)
    return JSONResponse(content=body)


@router.post("/artist-profiles/{profile_id}/voice/profiles/{voice_profile_id}/set-default")
def set_default_voice_profile(profile_id: str, voice_profile_id: str, request: Request,
                              owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    from sqlalchemy import select

    with request.app.state.db.session() as session:
        artist = _get_owned_profile(session, profile_id, owner_id)
        profile = session.get(VoiceProfile, voice_profile_id)
        if profile is None or profile.artist_profile_id != profile_id:
            raise ApiError(404, "VOICE_PROFILE_NOT_FOUND", "Voice profile not found.")
        for other in session.execute(
            select(VoiceProfile).where(VoiceProfile.artist_profile_id == profile_id)
        ).scalars():
            other.is_default = other.id == profile.id
        artist.default_voice_profile_id = profile.id
        session.commit()
    return JSONResponse(content={"artist_id": profile_id, "default_voice_profile_id": profile.id})
