"""Feature framework endpoints (milestone 9).

Minimal real implementations for controls shown in the reference mockups:
search, notifications, artifact export (MP3 via the audio worker, stems
pending a separator), and artist follows.
"""

from __future__ import annotations

from datetime import timedelta
import secrets

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
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
        outputs = ["mix_mp3"] if payload.format == "mp3" else ["stems_wav", "stems_zip"]
        request_json = {
            "source_version_id": version.id,
            "outputs": outputs,
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
            request_hash=f"asset-export:{asset.id}:{payload.format}",
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


@router.get("/public/tracks/{asset_id}")
def public_track(asset_id: str, request: Request) -> JSONResponse:
    """Single shared track for the public /track page."""
    from datetime import timedelta

    from ..tokens import make_token

    settings = request.app.state.settings
    now = utcnow()
    from ..deps import owner_from_request
    from ..models import Favorite

    try:
        viewer = owner_from_request(request)
    except ApiError:
        viewer = None
    with request.app.state.db.session() as session:
        asset = session.get(Asset, asset_id)
        if (
            asset is None
            or asset.deleted_at is not None
            or not asset.shared
            or asset.role != "mix_wav"
            or (asset.expires_at is not None and as_utc(asset.expires_at) <= now)
        ):
            raise ApiError(404, "NOT_FOUND", "Track not found.")
        from .jobs import _creator_names, _like_counts

        creator = _creator_names(session, {asset.owner_id}).get(asset.owner_id, "community")
        likes = _like_counts(session, [asset.id]).get(asset.id, 0)
        token = make_token(settings.secret_key, asset.id, now + timedelta(hours=24))
        owner_job = session.execute(select(Job).where(Job.id == asset.job_id)).scalar_one_or_none()
        operation = owner_job.operation if owner_job else None
        favorite = bool(
            viewer
            and session.execute(
                select(Favorite).where(Favorite.owner_id == viewer, Favorite.asset_id == asset.id)
            ).scalar_one_or_none()
        )
    return JSONResponse(
        {
            "asset_id": asset.id,
            "title": asset.title or "Untitled",
            "duration_seconds": asset.duration_seconds,
            "created_at": asset.created_at.isoformat() if asset.created_at else None,
            "like_count": likes,
            "favorite": favorite,
            "creator": creator,
            "operation": operation,
            "url": f"/api/v1/artifacts/{asset.id}/content?token={token}",
        }
    )


def _artist_stats(session, profile) -> dict:
    from sqlalchemy import func as sa_func

    from ..models import Asset, ArtistFollow, PlayEvent

    followers = session.execute(
        select(sa_func.count()).select_from(ArtistFollow).where(ArtistFollow.profile_id == profile.id)
    ).scalar_one()
    asset_ids = list(
        session.execute(
            select(Asset.id).where(
                Asset.owner_id == profile.owner_id,
                Asset.shared.is_(True),
                Asset.role == "mix_wav",
                Asset.deleted_at.is_(None),
            )
        ).scalars()
    )
    plays = 0
    if asset_ids:
        plays = int(
            session.execute(
                select(sa_func.count()).select_from(PlayEvent).where(PlayEvent.asset_id.in_(asset_ids))
            ).scalar_one()
        )
    return {
        "name": profile.name,
        "slug": profile.slug,
        "tracks": len(asset_ids),
        "followers": int(followers),
        "plays": plays,
    }


@router.get("/public/spotlight")
def public_spotlight(request: Request) -> JSONResponse:
    """Most-followed public artist, for the home spotlight card."""
    from sqlalchemy import func as sa_func

    from ..models import ArtistFollow

    with request.app.state.db.session() as session:
        row = session.execute(
            select(ArtistProfile)
            .outerjoin(ArtistFollow, ArtistFollow.profile_id == ArtistProfile.id)
            .where(ArtistProfile.sharing_policy == "public")
            .order_by(
                sa_func.count(ArtistFollow.id).desc(),
                ArtistProfile.name,
            )
            .group_by(ArtistProfile.id)
            .limit(1)
        ).first()
        if row is None:
            return JSONResponse({"artist": None})
        return JSONResponse({"artist": _artist_stats(session, row[0])})


@router.get("/public/artists/{slug}/stats")
def public_artist_stats(slug: str, request: Request) -> JSONResponse:
    with request.app.state.db.session() as session:
        profile = _profile_by_slug(session, slug)
        return JSONResponse(_artist_stats(session, profile))


@router.get("/artifacts/{asset_id}/stems")
def artifact_stems(asset_id: str, request: Request, owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    """List separated stem assets derived from a source asset."""
    from datetime import timedelta

    from ..tokens import make_token

    settings = request.app.state.settings
    now = utcnow()
    with request.app.state.db.session() as session:
        source = session.get(Asset, asset_id)
        if source is None or source.deleted_at is not None:
            raise ApiError(404, "NOT_FOUND", "Asset not found.")
        if source.owner_id != owner_id:
            raise ApiError(403, "FORBIDDEN", "Not your asset.")
        stems = list(
            session.execute(
                select(Asset)
                .where(Asset.source_asset_id == asset_id, Asset.stem_category.isnot(None), Asset.deleted_at.is_(None))
                .order_by(Asset.stem_category)
            ).scalars()
        )
        items = []
        for stem in stems:
            token = make_token(settings.secret_key, stem.id, now + timedelta(hours=24))
            items.append(
                {
                    "category": stem.stem_category,
                    "asset_id": stem.id,
                    "bytes": stem.bytes,
                    "created_at": stem.created_at.isoformat() if stem.created_at else None,
                    "url": f"/api/v1/artifacts/{stem.id}/content?token={token}",
                }
            )
        zip_asset = session.execute(
            select(Asset)
            .where(Asset.source_asset_id == asset_id, Asset.role == "stems_zip", Asset.deleted_at.is_(None))
            .order_by(Asset.created_at.desc())
            .limit(1)
        ).scalars().first()
        zip_info: dict | None = None
        if zip_asset is not None:
            ztok = make_token(settings.secret_key, zip_asset.id, now + timedelta(hours=24))
            zip_info = {"asset_id": zip_asset.id, "bytes": zip_asset.bytes,
                        "url": f"/api/v1/artifacts/{zip_asset.id}/content?token={ztok}"}
        elif items:
            zip_info = {"asset_id": None, "url": f"/api/v1/artifacts/{asset_id}/stems/zip"}
    return JSONResponse({"asset_id": asset_id, "stems": items, "zip": zip_info})


@router.get("/artifacts/{asset_id}/stems/zip")
def artifact_stems_zip(asset_id: str, request: Request, owner_id: str = Depends(owner_from_request)) -> Response:
    """Single ZIP of a source asset's stems. Prefers a stored ``stems_zip`` asset and
    otherwise assembles one on the fly (covers tracks separated before auto-zip)."""
    from urllib.parse import quote

    from ..audio_processing import build_stems_zip

    storage = request.app.state.storage
    with request.app.state.db.session() as session:
        source = session.get(Asset, asset_id)
        if source is None or source.deleted_at is not None:
            raise ApiError(404, "NOT_FOUND", "Asset not found.")
        if source.owner_id != owner_id:
            raise ApiError(403, "FORBIDDEN", "Not your asset.")
        zip_asset = session.execute(
            select(Asset)
            .where(Asset.source_asset_id == asset_id, Asset.role == "stems_zip", Asset.deleted_at.is_(None))
            .order_by(Asset.created_at.desc())
            .limit(1)
        ).scalars().first()
        stems = list(
            session.execute(
                select(Asset)
                .where(Asset.source_asset_id == asset_id, Asset.stem_category.isnot(None), Asset.deleted_at.is_(None))
                .order_by(Asset.stem_category)
            ).scalars()
        )
    if zip_asset is not None:
        body = storage.get(zip_asset.storage_key).body
    elif stems:
        bundle = {s.stem_category: storage.get(s.storage_key).body for s in stems}
        body = build_stems_zip(bundle, {"source_asset_id": asset_id, "title": source.title, "stems": sorted(bundle)})
    else:
        raise ApiError(404, "NO_STEMS", "No separated stems for this asset.")
    filename = quote(f"stems-{(source.title or asset_id)[:60]}.zip")
    return Response(content=body, media_type="application/zip",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"})
