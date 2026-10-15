"""Artist profiles, datasets, training/evaluation admission, activation.

Style and singer components stay distinct; training mechanisms are labeled
truthfully (`fine_tuned_adapter` only from real optimization). Versions are
immutable; activation/rollback use optimistic concurrency.
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select

from ..deps import owner_from_request
from ..errors import ApiError
from ..models import (
    ArtistProfile,
    ArtistProfileVersion,
    Asset,
    Dataset,
    DatasetTrack,
    DatasetVersion,
    Evaluation,
    IdempotencyRecord,
    Job,
    RightsRecord,
    TrainingRun,
    new_uuid,
    utcnow,
)
from ..orchestration import append_event, enqueue
from ..registry import MODEL_RELEASES
from ..routes.jobs import _idempotency_key
from ..schemas import (
    ActivateRequest,
    ArtistProfileCreate,
    ArtistProfilePatch,
    ArtistProfileResponse,
    DatasetCreate,
    DatasetResponse,
    DatasetVersionResponse,
    EvaluationCreate,
    JobAcceptedResponse,
    ProfileVersionResponse,
    ReviewRequest,
    RightsCreate,
    RightsResponse,
    TrackCreate,
    TrackResponse,
    TrainingCreate,
)

router = APIRouter(tags=["artist"])

RIGHTS_PURPOSES = ("recording", "composition", "singer_identity", "other")


def _profile_response(profile: ArtistProfile) -> ArtistProfileResponse:
    return ArtistProfileResponse(
        profile_id=profile.id,
        name=profile.name,
        style=profile.style_json,
        singer=profile.singer_json,
        sharing_policy=profile.sharing_policy,
        active_version_id=profile.active_version_id,
        etag=f'"{profile.etag_version}"',
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def _get_owned_profile(session, profile_id: str, owner_id: str) -> ArtistProfile:
    profile = session.get(ArtistProfile, profile_id)
    if profile is None or profile.owner_id != owner_id or profile.deleted_at is not None:
        raise ApiError(404, "PROFILE_NOT_FOUND", "Artist profile not found.")
    return profile


def _require_if_match(request: Request, profile: ArtistProfile) -> None:
    header = request.headers.get("If-Match")
    if header is None:
        raise ApiError(428, "PRECONDITION_REQUIRED", "This operation requires an If-Match header.")
    if header.strip().strip('"') != str(profile.etag_version):
        raise ApiError(412, "ETAG_MISMATCH", "If-Match does not match the current profile revision.",
                       {"current_etag": f'"{profile.etag_version}"'})


def _version_response(version: ArtistProfileVersion) -> ProfileVersionResponse:
    return ProfileVersionResponse(
        version_id=version.id,
        profile_id=version.profile_id,
        mechanism=version.mechanism,
        base_model_id=version.base_model_id,
        base_revision=version.base_revision,
        recipe_revision=version.recipe_revision,
        dataset_version_id=version.dataset_version_id,
        artifacts=version.artifacts_json,
        evaluation_status=version.evaluation_status,
        state=version.state,
        created_at=version.created_at,
    )


def _get_owned_dataset(session, dataset_id: str, owner_id: str) -> Dataset:
    dataset = session.get(Dataset, dataset_id)
    if dataset is None or dataset.owner_id != owner_id or dataset.deleted_at is not None:
        raise ApiError(404, "DATASET_NOT_FOUND", "Dataset not found.")
    return dataset


def _accepted(job: Job, request: Request) -> JSONResponse:
    settings = request.app.state.settings
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


def _create_job(session, request: Request, owner_id: str, route: str, operation: str,
                model_id: str, model_revision: str, request_json: dict, request_hash: str) -> tuple[Job, bool]:
    settings = request.app.state.settings
    key = _idempotency_key(request, settings.max_idempotency_key_length)
    existing = session.execute(
        select(IdempotencyRecord).where(
            IdempotencyRecord.owner_id == owner_id,
            IdempotencyRecord.route == route,
            IdempotencyRecord.key == key,
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.request_hash != request_hash:
            raise ApiError(409, "IDEMPOTENCY_CONFLICT", "Idempotency-Key was already used with a different request.",
                           {"job_id": existing.job_id})
        job = session.execute(select(Job).where(Job.id == existing.job_id)).scalar_one()
        return job, False
    job = Job(
        id=new_uuid(),
        owner_id=owner_id,
        operation=operation,
        model_id=model_id,
        model_revision=model_revision,
        status="queued",
        request_json=request_json,
        request_hash=request_hash,
        idempotency_key=key,
    )
    session.add(job)
    session.add(
        IdempotencyRecord(
            owner_id=owner_id,
            route=route,
            key=key,
            request_hash=request_hash,
            job_id=job.id,
            expires_at=utcnow() + timedelta(hours=settings.idempotency_retention_hours),
        )
    )
    enqueue(session, job, settings)
    append_event(session, job.id, "queued", "queued")
    return job, True



# --- profiles --------------------------------------------------------------


@router.post("/artist-profiles", status_code=201)
def create_profile(payload: ArtistProfileCreate, request: Request, owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    with request.app.state.db.session() as session:
        profile = ArtistProfile(id=new_uuid(), owner_id=owner_id, name=payload.name,
                                style_json=payload.style, singer_json=payload.singer)
        session.add(profile)
        session.commit()
        body = _profile_response(profile)
    return JSONResponse(status_code=201, content=body.model_dump(mode="json"), headers={"ETag": body.etag})


@router.get("/artist-profiles")
def list_profiles(request: Request, owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    with request.app.state.db.session() as session:
        rows = list(session.execute(
            select(ArtistProfile)
            .where(ArtistProfile.owner_id == owner_id, ArtistProfile.deleted_at.is_(None))
            .order_by(ArtistProfile.created_at.desc())
        ).scalars())
    return JSONResponse(content=[_profile_response(p).model_dump(mode="json") for p in rows])


@router.get("/artist-profiles/{profile_id}")
def get_profile(profile_id: str, request: Request, owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    with request.app.state.db.session() as session:
        body = _profile_response(_get_owned_profile(session, profile_id, owner_id))
    return JSONResponse(content=body.model_dump(mode="json"), headers={"ETag": body.etag})


@router.patch("/artist-profiles/{profile_id}")
def patch_profile(profile_id: str, payload: ArtistProfilePatch, request: Request,
                  owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    with request.app.state.db.session() as session:
        profile = _get_owned_profile(session, profile_id, owner_id)
        _require_if_match(request, profile)
        if payload.name is not None:
            profile.name = payload.name
        if payload.style is not None:
            profile.style_json = payload.style
        if payload.singer is not None:
            profile.singer_json = payload.singer
        profile.etag_version += 1
        session.commit()
        body = _profile_response(profile)
    return JSONResponse(content=body.model_dump(mode="json"), headers={"ETag": body.etag})


@router.delete("/artist-profiles/{profile_id}", status_code=204)
def delete_profile(profile_id: str, request: Request, owner_id: str = Depends(owner_from_request)) -> Response:
    with request.app.state.db.session() as session:
        profile = _get_owned_profile(session, profile_id, owner_id)
        profile.deleted_at = utcnow()
        session.commit()
    return Response(status_code=204)


# --- rights ----------------------------------------------------------------


@router.post("/artist-profiles/{profile_id}/rights", status_code=201)
def add_rights(profile_id: str, payload: RightsCreate, request: Request,
               owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    if payload.purpose not in RIGHTS_PURPOSES:
        raise ApiError(422, "RIGHTS_PURPOSE_UNSUPPORTED", "Unknown rights purpose.",
                       {"supported": list(RIGHTS_PURPOSES)})
    with request.app.state.db.session() as session:
        _get_owned_profile(session, profile_id, owner_id)
        record = RightsRecord(id=new_uuid(), owner_id=owner_id, profile_id=profile_id,
                              asset_id=payload.asset_id, purpose=payload.purpose, declaration=payload.declaration)
        session.add(record)
        session.commit()
        body = RightsResponse(record_id=record.id, profile_id=record.profile_id, asset_id=record.asset_id,
                              purpose=record.purpose, declaration=record.declaration, declared_at=record.declared_at)
    return JSONResponse(status_code=201, content=body.model_dump(mode="json"))


@router.get("/artist-profiles/{profile_id}/rights")
def list_rights(profile_id: str, request: Request, owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    with request.app.state.db.session() as session:
        _get_owned_profile(session, profile_id, owner_id)
        rows = list(session.execute(
            select(RightsRecord).where(RightsRecord.profile_id == profile_id).order_by(RightsRecord.declared_at)
        ).scalars())
    return JSONResponse(content=[
        RightsResponse(record_id=r.id, profile_id=r.profile_id, asset_id=r.asset_id, purpose=r.purpose,
                       declaration=r.declaration, declared_at=r.declared_at).model_dump(mode="json")
        for r in rows
    ])


# --- datasets ---------------------------------------------------------------


@router.post("/artist-profiles/{profile_id}/datasets", status_code=201)
def create_dataset(profile_id: str, payload: DatasetCreate, request: Request,
                   owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    with request.app.state.db.session() as session:
        _get_owned_profile(session, profile_id, owner_id)
        dataset = Dataset(id=new_uuid(), owner_id=owner_id, profile_id=profile_id, name=payload.name)
        session.add(dataset)
        session.commit()
        body = DatasetResponse(dataset_id=dataset.id, profile_id=dataset.profile_id, name=dataset.name,
                               status=dataset.status, created_at=dataset.created_at)
    return JSONResponse(status_code=201, content=body.model_dump(mode="json"))


@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: str, request: Request, owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    with request.app.state.db.session() as session:
        dataset = _get_owned_dataset(session, dataset_id, owner_id)
        body = DatasetResponse(dataset_id=dataset.id, profile_id=dataset.profile_id, name=dataset.name,
                               status=dataset.status, created_at=dataset.created_at)
    return JSONResponse(content=body.model_dump(mode="json"))


@router.post("/datasets/{dataset_id}/tracks", status_code=201)
def add_track(dataset_id: str, payload: TrackCreate, request: Request,
              owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    with request.app.state.db.session() as session:
        dataset = _get_owned_dataset(session, dataset_id, owner_id)
        if dataset.status != "open":
            raise ApiError(409, "STATE_CONFLICT", "Only open datasets accept new tracks.")
        asset = session.get(Asset, payload.asset_id)
        if asset is None or asset.owner_id != owner_id:
            raise ApiError(404, "ASSET_NOT_FOUND", "Asset not found.")
        if asset.deleted_at is not None:
            raise ApiError(410, "ASSET_DELETED", "Asset has been revoked.")
        duplicate = session.execute(
            select(DatasetTrack).where(DatasetTrack.dataset_id == dataset.id, DatasetTrack.asset_id == payload.asset_id)
        ).scalar_one_or_none()
        if duplicate is not None:
            raise ApiError(409, "TRACK_DUPLICATE", "Asset is already in this dataset.")
        track = DatasetTrack(id=new_uuid(), dataset_id=dataset.id, owner_id=owner_id, asset_id=payload.asset_id,
                             lyrics=payload.lyrics, language=payload.language, labels_json=payload.labels)
        session.add(track)
        session.commit()
        body = TrackResponse(track_id=track.id, dataset_id=track.dataset_id, asset_id=track.asset_id,
                             lyrics=track.lyrics, language=track.language, labels=track.labels_json, split=track.split)
    return JSONResponse(status_code=201, content=body.model_dump(mode="json"))


@router.get("/datasets/{dataset_id}/tracks")
def list_tracks(dataset_id: str, request: Request, owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    with request.app.state.db.session() as session:
        _get_owned_dataset(session, dataset_id, owner_id)
        rows = list(session.execute(
            select(DatasetTrack).where(DatasetTrack.dataset_id == dataset_id).order_by(DatasetTrack.created_at)
        ).scalars())
    return JSONResponse(content=[
        TrackResponse(track_id=t.id, dataset_id=t.dataset_id, asset_id=t.asset_id, lyrics=t.lyrics,
                      language=t.language, labels=t.labels_json, split=t.split).model_dump(mode="json")
        for t in rows
    ])


@router.post("/datasets/{dataset_id}/finalize", status_code=201)
def finalize_dataset(dataset_id: str, request: Request, owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    with request.app.state.db.session() as session:
        dataset = _get_owned_dataset(session, dataset_id, owner_id)
        if dataset.status != "open":
            raise ApiError(409, "STATE_CONFLICT", "Dataset is already finalized.")
        tracks = list(session.execute(
            select(DatasetTrack).where(DatasetTrack.dataset_id == dataset.id).order_by(DatasetTrack.created_at, DatasetTrack.id)
        ).scalars())
        if not tracks:
            raise ApiError(422, "DATASET_EMPTY", "Finalize requires at least one track.")
        ordered = sorted(tracks, key=lambda t: (t.created_at, t.id))
        if len(ordered) >= 3:
            splits = {t.id: ("holdout" if i == len(ordered) - 1 else "validation" if i == len(ordered) - 2 else "train")
                      for i, t in enumerate(ordered)}
        elif len(ordered) == 2:
            splits = {ordered[0].id: "train", ordered[1].id: "holdout"}
        else:
            splits = {ordered[0].id: "train"}
        for track in tracks:
            track.split = splits[track.id]
        hash_material = []
        total_duration = 0.0
        for track in sorted(ordered, key=lambda t: t.id):
            asset = session.get(Asset, track.asset_id)
            total_duration += asset.duration_seconds or 0.0
            hash_material.append(f"{asset.sha256}|{track.lyrics or ''}|{json.dumps(track.labels_json, sort_keys=True)}")
        frozen = hashlib.sha256("\n".join(hash_material).encode("utf-8")).hexdigest()
        counts = {"train": 0, "validation": 0, "holdout": 0}
        for split in splits.values():
            counts[split] += 1
        warnings = []
        if counts["holdout"] == 0:
            warnings.append("no holdout recording: evaluation leakage cannot be excluded")
        if counts["train"] == 1:
            warnings.append("single training recording: style/singer generalization is limited")
        version_number = len(list(session.execute(
            select(DatasetVersion).where(DatasetVersion.dataset_id == dataset.id)
        ).scalars())) + 1
        version = DatasetVersion(
            id=new_uuid(), dataset_id=dataset.id, owner_id=owner_id, version_number=version_number,
            frozen_sha256=frozen,
            split_json={"tracks": [{"track_id": t.id, "asset_id": t.asset_id, "split": splits[t.id]} for t in ordered],
                        **counts},
            report_json={"recordings": len(ordered), "total_duration_seconds": round(total_duration, 3),
                         "warnings": warnings},
        )
        session.add(version)
        dataset.status = "finalized"
        session.commit()
        body = DatasetVersionResponse(dataset_version_id=version.id, dataset_id=version.dataset_id,
                                      version_number=version.version_number, frozen_sha256=version.frozen_sha256,
                                      split=version.split_json, report=version.report_json, created_at=version.created_at)
    return JSONResponse(status_code=201, content=body.model_dump(mode="json"))


@router.get("/dataset-versions/{dataset_version_id}")
def get_dataset_version(dataset_version_id: str, request: Request,
                        owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    with request.app.state.db.session() as session:
        version = session.get(DatasetVersion, dataset_version_id)
        if version is None or version.owner_id != owner_id:
            raise ApiError(404, "DATASET_VERSION_NOT_FOUND", "Dataset version not found.")
        body = DatasetVersionResponse(dataset_version_id=version.id, dataset_id=version.dataset_id,
                                      version_number=version.version_number, frozen_sha256=version.frozen_sha256,
                                      split=version.split_json, report=version.report_json, created_at=version.created_at)
    return JSONResponse(content=body.model_dump(mode="json"))


# --- training / evaluation admission ----------------------------------------


@router.post("/trainings", status_code=202)
def create_training(payload: TrainingCreate, request: Request,
                    owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    settings = request.app.state.settings
    base_model_id = payload.base_model_id or "ace-step-1.5"
    if base_model_id not in MODEL_RELEASES:
        raise ApiError(422, "MODEL_UNKNOWN", "Unknown base model.", {"known_models": sorted(MODEL_RELEASES)})
    budget = payload.budget or {}
    max_epochs = int(budget.get("max_epochs", 200))
    max_wall = int(budget.get("max_wall_seconds", settings.train_max_wall_seconds))
    if not 1 <= max_epochs <= settings.train_max_epochs:
        raise ApiError(422, "BUDGET_EXCEEDED", "Training epoch budget outside server limits.",
                       {"max_epochs_limit": settings.train_max_epochs})
    if not 1 <= max_wall <= settings.train_max_wall_seconds:
        raise ApiError(422, "BUDGET_EXCEEDED", "Training wall-clock budget outside server limits.",
                       {"max_wall_seconds_limit": settings.train_max_wall_seconds})
    request_hash = payload.request_hash()
    with request.app.state.db.session() as session:
        profile = _get_owned_profile(session, payload.profile_id, owner_id)
        dataset_version = session.get(DatasetVersion, payload.dataset_version_id)
        if dataset_version is None or dataset_version.owner_id != owner_id:
            raise ApiError(404, "DATASET_VERSION_NOT_FOUND", "Dataset version not found.")
        dataset = _get_owned_dataset(session, dataset_version.dataset_id, owner_id)
        if dataset.profile_id != profile.id:
            raise ApiError(422, "DATASET_PROFILE_MISMATCH", "Dataset version belongs to another profile.")
        if dataset.status != "finalized":
            raise ApiError(409, "STATE_CONFLICT", "Dataset must be finalized before training.")
        recipe = payload.recipe_revision or settings.train_recipe_revision
        request_json = payload.model_dump(mode="json")
        request_json["recipe_revision"] = recipe
        job, created = _create_job(session, request, owner_id, "POST /trainings", "artist.train",
                                   settings.train_queue_model_id, recipe, request_json, request_hash)
        if created:
            session.add(TrainingRun(id=new_uuid(), job_id=job.id, budget_json={"max_epochs": max_epochs,
                              "max_wall_seconds": max_wall}, hyperparams_json=payload.hyperparams,
                              seed=payload.seed, status="queued"))
        session.commit()
    return _accepted(job, request)


@router.post("/evaluations", status_code=202)
def create_evaluation(payload: EvaluationCreate, request: Request,
                      owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    settings = request.app.state.settings
    request_hash = payload.request_hash()
    with request.app.state.db.session() as session:
        version = session.get(ArtistProfileVersion, payload.profile_version_id)
        if version is None or version.owner_id != owner_id:
            raise ApiError(404, "PROFILE_VERSION_NOT_FOUND", "Profile version not found.")
        job, created = _create_job(session, request, owner_id, "POST /evaluations", "artist.evaluate",
                                   settings.evaluate_queue_model_id, version.recipe_revision,
                                   payload.model_dump(mode="json"), request_hash)
        if created:
            session.add(Evaluation(id=new_uuid(), profile_version_id=version.id, job_id=job.id,
                                   prompts_json=payload.prompts))
        session.commit()
    return _accepted(job, request)


@router.get("/artist-profiles/{profile_id}/versions")
def list_profile_versions(profile_id: str, request: Request,
                          owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    with request.app.state.db.session() as session:
        _get_owned_profile(session, profile_id, owner_id)
        rows = list(session.execute(
            select(ArtistProfileVersion)
            .where(ArtistProfileVersion.profile_id == profile_id)
            .order_by(ArtistProfileVersion.created_at.desc())
        ).scalars())
    return JSONResponse(content=[_version_response(v).model_dump(mode="json") for v in rows])


@router.post("/artist-profiles/{profile_id}/activate")
def activate_profile_version(profile_id: str, payload: ActivateRequest, request: Request,
                             owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    with request.app.state.db.session() as session:
        profile = _get_owned_profile(session, profile_id, owner_id)
        _require_if_match(request, profile)
        version = session.get(ArtistProfileVersion, payload.version_id)
        if version is None or version.profile_id != profile.id or version.owner_id != owner_id:
            raise ApiError(404, "PROFILE_VERSION_NOT_FOUND", "Profile version not found.")
        if version.state == "active":
            raise ApiError(409, "STATE_CONFLICT", "Version is already active.")
        if version.evaluation_status != "measured":
            raise ApiError(409, "PROFILE_NOT_EVALUATED", "Only measured candidates can become active.")
        if profile.active_version_id:
            previous = session.get(ArtistProfileVersion, profile.active_version_id)
            if previous is not None:
                previous.state = "retired"
        version.state = "active"
        profile.active_version_id = version.id
        profile.etag_version += 1
        session.commit()
        body = _profile_response(profile)
    return JSONResponse(content=body.model_dump(mode="json"), headers={"ETag": body.etag})


@router.post("/evaluations/{evaluation_id}/review")
def review_evaluation(evaluation_id: str, payload: ReviewRequest, request: Request,
                      owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    with request.app.state.db.session() as session:
        evaluation = session.get(Evaluation, evaluation_id)
        if evaluation is None:
            raise ApiError(404, "EVALUATION_NOT_FOUND", "Evaluation not found.")
        version = session.get(ArtistProfileVersion, evaluation.profile_version_id)
        if version is None or version.owner_id != owner_id:
            raise ApiError(404, "EVALUATION_NOT_FOUND", "Evaluation not found.")
        evaluation.review = payload.review
        session.commit()
    return JSONResponse(content={"evaluation_id": evaluation.id, "review": evaluation.review})
