"""Feature framework endpoints (milestone 9).

Minimal real implementations for controls shown in the reference mockups:
search, notifications, artifact export (MP3 via the audio worker, stems
pending a separator), and artist follows.
"""

from __future__ import annotations

from datetime import timedelta
import secrets

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import func, select

from ..auth import token_sha256
from ..deps import owner_from_request
from ..errors import ApiError
from ..models import (
    ApiKey,
    ArtistFollow,
    ArtistProfile,
    Asset,
    Job,
    ProjectVersion,
    new_uuid,
    utcnow,
)
from ..orchestration import append_event, as_utc, enqueue
from ..schemas import StrictModel

router = APIRouter(tags=["features"])


@router.get("/search")
def search(request: Request, q: str = Query(min_length=2, max_length=100)) -> JSONResponse:
    now = utcnow()
    pattern = f"%{q.strip()}%"
    with request.app.state.db.session() as session:
        tracks = list(
            session.execute(
                select(Asset)
                .where(
                    Asset.shared.is_(True),
                    Asset.deleted_at.is_(None),
                    Asset.role == "mix_wav",
                    Asset.title.is_not(None),
                    Asset.title.ilike(pattern),
                )
                .order_by(Asset.created_at.desc())
                .limit(10)
            ).scalars()
        )
        artists = list(
            session.execute(
                select(ArtistProfile)
                .where(
                    ArtistProfile.sharing_policy == "public",
                    ArtistProfile.name.ilike(pattern),
                )
                .order_by(ArtistProfile.name)
                .limit(5)
            ).scalars()
        )
    track_items = [
        {
            "asset_id": a.id,
            "title": a.title,
            "duration_seconds": a.duration_seconds,
            "url": f"/api/v1/artifacts/{a.id}/content",
        }
        for a in tracks
        if a.expires_at is None or as_utc(a.expires_at) > now
    ]
    artist_items = [{"name": p.name, "slug": p.slug} for p in artists]
    return JSONResponse({"query": q, "tracks": track_items, "artists": artist_items})


@router.get("/notifications")
def notifications(request: Request, owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    since = utcnow() - timedelta(days=7)
    with request.app.state.db.session() as session:
        jobs = list(
            session.execute(
                select(Job)
                .where(Job.owner_id == owner_id, Job.created_at >= since)
                .order_by(Job.created_at.desc())
                .limit(20)
            ).scalars()
        )
    items = []
    for job in jobs:
        prompt = (job.request_json or {}).get("prompt") or ""
        items.append(
            {
                "job_id": job.id,
                "operation": job.operation,
                "status": job.status,
                "title": (prompt[:60] or job.operation),
                "created_at": job.created_at.isoformat() if job.created_at else None,
            }
        )
    active = sum(1 for i in items if i["status"] in ("queued", "waiting_for_worker", "running"))
    return JSONResponse({"notifications": items, "active_count": active})


class ExportFormatRequest(StrictModel):
    format: str = Field(pattern="^(mp3|stems)$")


@router.post("/artifacts/{asset_id}/export", status_code=202)
def export_artifact(
    asset_id: str,
    payload: ExportFormatRequest,
    request: Request,
    owner_id: str = Depends(owner_from_request),
) -> JSONResponse:
    settings = request.app.state.settings
    if payload.format == "stems":
        raise ApiError(501, "COMING_SOON", "Stem separation is coming soon.")
    with request.app.state.db.session() as session:
        asset = session.get(Asset, asset_id)
        if asset is None or asset.deleted_at is not None:
            raise ApiError(404, "ASSET_NOT_FOUND", "Asset not found.")
        if asset.owner_id != owner_id:
            raise ApiError(403, "FORBIDDEN", "Not your asset.")
        version = ProjectVersion(
            project_id=asset.job_id,
            owner_id=owner_id,
            kind="generated",
            label=asset.title,
            source_job_id=asset.job_id,
            source_asset_id=asset.id,
        )
        session.add(version)
        session.flush()
        request_json = {
            "source_version_id": version.id,
            "outputs": ["mix_mp3"],
            "mp3": {"bitrate_kbps": 320},
            "stem_set": "available",
        }
        job = Job(
            id=new_uuid(),
            owner_id=owner_id,
            operation="audio.export",
            model_id="audio-export",
            model_revision="mp3-1",
            status="queued",
            request_json=request_json,
            request_hash=f"asset-export:{asset.id}:mp3",
            idempotency_key=new_uuid(),
        )
        session.add(job)
        enqueue(session, job, settings)
        append_event(session, job.id, "queued", "queued")
        session.commit()
        job_id = job.id
    return JSONResponse(
        status_code=202,
        content={"job_id": job_id, "status": "queued", "asset_id": asset_id, "format": payload.format},
        headers={"Location": f"/api/v1/jobs/{job_id}"},
    )


@router.get("/trainings")
def my_trainings(request: Request, owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    from ..models import TrainingRun

    with request.app.state.db.session() as session:
        rows = list(
            session.execute(
                select(TrainingRun, Job)
                .join(Job, TrainingRun.job_id == Job.id)
                .where(Job.owner_id == owner_id)
                .order_by(Job.created_at.desc())
                .limit(20)
            )
        )
    items = [
        {
            "run_id": run.id,
            "job_id": job.id,
            "status": run.status,
            "stage": (run.metrics_json or {}).get("stage"),
            "progress": (run.metrics_json or {}).get("progress"),
            "hardware": run.hardware,
            "created_at": job.created_at.isoformat() if job.created_at else None,
        }
        for run, job in rows
    ]
    return JSONResponse({"trainings": items})


def _profile_by_slug(session, slug: str) -> ArtistProfile:
    profile = session.execute(
        select(ArtistProfile).where(ArtistProfile.slug == slug, ArtistProfile.sharing_policy == "public")
    ).scalar_one_or_none()
    if profile is None:
        raise ApiError(404, "ARTIST_NOT_FOUND", "Artist not found.")
    return profile


def _follow_state(session, profile_id: str, owner_id: str) -> dict:
    count = session.execute(
        select(func.count()).select_from(ArtistFollow).where(ArtistFollow.profile_id == profile_id)
    ).scalar_one()
    following = (
        session.execute(
            select(ArtistFollow).where(ArtistFollow.profile_id == profile_id, ArtistFollow.owner_id == owner_id)
        ).scalar_one_or_none()
        is not None
    )
    return {"following": following, "follower_count": count}


@router.post("/public/artists/{slug}/follow")
def follow_artist(slug: str, request: Request, owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    with request.app.state.db.session() as session:
        profile = _profile_by_slug(session, slug)
        existing = session.execute(
            select(ArtistFollow).where(ArtistFollow.profile_id == profile.id, ArtistFollow.owner_id == owner_id)
        ).scalar_one_or_none()
        if existing is None:
            session.add(ArtistFollow(owner_id=owner_id, profile_id=profile.id))
            session.commit()
        return JSONResponse(_follow_state(session, profile.id, owner_id))


@router.delete("/public/artists/{slug}/follow")
def unfollow_artist(slug: str, request: Request, owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    with request.app.state.db.session() as session:
        profile = _profile_by_slug(session, slug)
        existing = session.execute(
            select(ArtistFollow).where(ArtistFollow.profile_id == profile.id, ArtistFollow.owner_id == owner_id)
        ).scalar_one_or_none()
        if existing is not None:
            session.delete(existing)
            session.commit()
        return JSONResponse(_follow_state(session, profile.id, owner_id))


class ApiKeyCreate(StrictModel):
    name: str = Field(min_length=1, max_length=120)


def _key_dict(key: ApiKey) -> dict:
    return {
        "id": key.id,
        "name": key.name,
        "prefix": key.key_prefix,
        "created_at": key.created_at.isoformat(),
        "revoked_at": key.revoked_at.isoformat() if key.revoked_at else None,
        "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
    }


@router.get("/api-keys")
def list_api_keys(request: Request, owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    with request.app.state.db.session() as session:
        keys = list(
            session.execute(
                select(ApiKey)
                .where(ApiKey.owner_id == owner_id)
                .order_by(ApiKey.created_at.desc())
            ).scalars()
        )
        return JSONResponse({"items": [_key_dict(k) for k in keys]})


@router.post("/api-keys", status_code=201)
def create_api_key(
    payload: ApiKeyCreate, request: Request, owner_id: str = Depends(owner_from_request)
) -> JSONResponse:
    secret = "oal_" + secrets.token_urlsafe(30)
    key = ApiKey(
        owner_id=owner_id,
        name=payload.name.strip(),
        key_sha256=token_sha256(secret),
        key_prefix=secret[:12],
    )
    with request.app.state.db.session() as session:
        session.add(key)
        session.commit()
        body = _key_dict(key)
    body["secret"] = secret
    return JSONResponse(body, status_code=201)


@router.delete("/api-keys/{key_id}")
def revoke_api_key(key_id: str, request: Request, owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    with request.app.state.db.session() as session:
        key = session.get(ApiKey, key_id)
        if key is None or key.owner_id != owner_id:
            raise ApiError(404, "NOT_FOUND", "API key not found.")
        if key.revoked_at is None:
            key.revoked_at = utcnow()
            session.commit()
        return JSONResponse(_key_dict(key))
