"""Artist profiles (UAIS canonical identity records).

Style and singer components stay distinct; the voice identity itself lives in
the UAIS voice tables (see app/routes/voice.py). Versions are immutable;
activation/rollback use optimistic concurrency.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy import func, select

from ..deps import owner_from_request
from ..errors import ApiError
from ..models import (
    ArtistProfile,
    ArtistSong,
    Asset,
    IdempotencyRecord,
    Job,
    new_uuid,
    utcnow,
)
from ..orchestration import append_event, enqueue
from ..routes.jobs import _idempotency_key
from ..schemas import (
    ArtistProfileCreate,
    ArtistProfilePatch,
    ArtistProfileResponse,
    JobAcceptedResponse,
)

router = APIRouter(tags=["artist"])


def _profile_response(profile: ArtistProfile) -> ArtistProfileResponse:
    return ArtistProfileResponse(
        profile_id=profile.id,
        name=profile.name,
        slug=profile.slug,
        bio=profile.bio,
        avatar_key=profile.avatar_key,
        style=profile.style_json,
        singer=profile.singer_json,
        sharing_policy=profile.sharing_policy,
        default_voice_profile_id=profile.default_voice_profile_id,
        is_main=profile.is_main,
        etag=f'"{profile.etag_version}"',
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def _unique_slug(session, name: str) -> str:
    import re

    from sqlalchemy import select as _select

    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:200] or "artist"
    slug = base
    counter = 2
    while session.execute(_select(ArtistProfile).where(ArtistProfile.slug == slug)).scalar_one_or_none() is not None:
        slug = f"{base}-{counter}"
        counter += 1
    return slug


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
        has_existing = (
            session.execute(
                select(ArtistProfile.id).where(
                    ArtistProfile.owner_id == owner_id, ArtistProfile.deleted_at.is_(None)
                ).limit(1)
            ).first()
            is not None
        )
        profile = ArtistProfile(id=new_uuid(), owner_id=owner_id, name=payload.name,
                                style_json=payload.style, singer_json=payload.singer,
                                bio=payload.bio, is_main=not has_existing,
                                slug=_unique_slug(session, payload.name))
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
        if payload.sharing is not None:
            profile.sharing_policy = payload.sharing
        if payload.bio is not None:
            profile.bio = payload.bio
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


@router.post("/artist-profiles/{profile_id}/set-main")
def set_main_profile(profile_id: str, request: Request, owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    """Designate this artist as the account's Main profile (exactly one per owner)."""
    with request.app.state.db.session() as session:
        profile = _get_owned_profile(session, profile_id, owner_id)
        for other in session.execute(
            select(ArtistProfile).where(
                ArtistProfile.owner_id == owner_id,
                ArtistProfile.deleted_at.is_(None),
                ArtistProfile.id != profile.id,
            )
        ).scalars():
            other.is_main = False
        profile.is_main = True
        session.commit()
        body = _profile_response(profile)
    return JSONResponse(content=body.model_dump(mode="json"), headers={"ETag": body.etag})


# --- M17: artist avatar + curated songs --------------------------------------


class ArtistSongCreate(BaseModel):
    asset_id: str


@router.post("/artist-profiles/{profile_id}/avatar", status_code=201)
async def upload_artist_avatar(
    profile_id: str,
    request: Request,
    owner_id: str = Depends(owner_from_request),
    file: UploadFile = File(...),
) -> JSONResponse:
    from .auth import AVATAR_MAX_BYTES, AVATAR_MEDIA

    content_type = (file.content_type or "").lower()
    if not content_type.startswith("image/"):
        raise ApiError(422, "INVALID_FILE", "Avatar must be an image.")
    body = await file.read()
    if not body:
        raise ApiError(422, "EMPTY_FILE", "Avatar file is empty.")
    if len(body) > AVATAR_MAX_BYTES:
        raise ApiError(413, "FILE_TOO_LARGE", "Avatar must be 2 MB or smaller.")
    suffix = ".png" if content_type == "image/png" else ".jpg"
    for ext in AVATAR_MEDIA:
        if (file.filename or "").lower().endswith(ext):
            suffix = ext
            break
    key = f"owners/{owner_id}/artist-avatar-{new_uuid()}{suffix}"
    request.app.state.storage.put(key, body)
    with request.app.state.db.session() as session:
        profile = _get_owned_profile(session, profile_id, owner_id)
        profile.avatar_key = key
        profile.etag_version += 1
        session.commit()
    return JSONResponse(status_code=201, content={"ok": True, "avatar_key": key})


@router.get("/artist-profiles/{profile_id}/avatar")
def get_artist_avatar(profile_id: str, request: Request) -> Response:
    from .auth import AVATAR_MEDIA

    with request.app.state.db.session() as session:
        profile = session.get(ArtistProfile, profile_id)
    if profile is None or not profile.avatar_key:
        raise ApiError(404, "AVATAR_NOT_FOUND", "Artist has no avatar.")
    stored = request.app.state.storage.get(profile.avatar_key)
    media = AVATAR_MEDIA.get(profile.avatar_key[profile.avatar_key.rfind("."):].lower(), "application/octet-stream")
    return Response(content=stored.body, media_type=media, headers={"Cache-Control": "public, max-age=300"})


@router.get("/artist-profiles/{profile_id}/songs")
def list_artist_songs(profile_id: str, request: Request,
                      owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    with request.app.state.db.session() as session:
        _get_owned_profile(session, profile_id, owner_id)
        rows = list(session.execute(
            select(ArtistSong, Asset)
            .join(Asset, Asset.id == ArtistSong.asset_id)
            .where(ArtistSong.profile_id == profile_id, Asset.deleted_at.is_(None))
            .order_by(ArtistSong.position, ArtistSong.created_at)
        ).all())
    return JSONResponse(content=[
        {"song_id": s.id, "asset_id": a.id, "title": a.title, "position": s.position}
        for s, a in rows
    ])


@router.post("/artist-profiles/{profile_id}/songs", status_code=201)
def add_artist_song(profile_id: str, payload: ArtistSongCreate, request: Request,
                    owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    with request.app.state.db.session() as session:
        _get_owned_profile(session, profile_id, owner_id)
        asset = session.get(Asset, payload.asset_id)
        if asset is None or asset.owner_id != owner_id:
            raise ApiError(404, "ASSET_NOT_FOUND", "Asset not found.")
        duplicate = session.execute(
            select(ArtistSong).where(ArtistSong.profile_id == profile_id, ArtistSong.asset_id == payload.asset_id)
        ).scalar_one_or_none()
        if duplicate is not None:
            raise ApiError(409, "SONG_DUPLICATE", "Song is already on this profile.")
        max_pos = session.execute(
            select(func.max(ArtistSong.position)).where(ArtistSong.profile_id == profile_id)
        ).scalar_one_or_none()
        song = ArtistSong(id=new_uuid(), profile_id=profile_id, owner_id=owner_id,
                          asset_id=payload.asset_id, position=(max_pos or 0) + 1)
        session.add(song)
        session.commit()
    return JSONResponse(status_code=201, content={"song_id": song.id, "asset_id": song.asset_id, "position": song.position})


@router.delete("/artist-profiles/{profile_id}/songs/{song_id}", status_code=204)
def remove_artist_song(profile_id: str, song_id: str, request: Request,
                       owner_id: str = Depends(owner_from_request)) -> Response:
    with request.app.state.db.session() as session:
        _get_owned_profile(session, profile_id, owner_id)
        song = session.get(ArtistSong, song_id)
        if song is None or song.profile_id != profile_id:
            raise ApiError(404, "SONG_NOT_FOUND", "Curated song not found on this profile.")
        session.delete(song)
        session.commit()
    return Response(status_code=204)


# --- public discovery (no auth) ---------------------------------------------


@router.get("/public/artists")
def public_artists(request: Request, limit: int = Query(default=50, ge=1, le=200)) -> JSONResponse:
    with request.app.state.db.session() as session:
        rows = list(
            session.execute(
                select(ArtistProfile)
                .where(
                    ArtistProfile.sharing_policy == "public",
                    ArtistProfile.deleted_at.is_(None),
                )
                .order_by(ArtistProfile.created_at.desc())
                .limit(limit)
            ).scalars()
        )
    return JSONResponse(
        [
            {
                "profile_id": p.id,
                "name": p.name,
                "slug": p.slug,
                "bio": p.bio,
                "avatar_url": f"/api/v1/artist-profiles/{p.id}/avatar" if p.avatar_key else None,
            }
            for p in rows
            if p.slug
        ]
    )


@router.get("/public/artists/{slug}")
def public_artist(slug: str, request: Request) -> JSONResponse:
    from ..models import Asset
    from ..tokens import make_token

    settings = request.app.state.settings
    with request.app.state.db.session() as session:
        profile = session.execute(
            select(ArtistProfile).where(
                ArtistProfile.slug == slug, ArtistProfile.deleted_at.is_(None)
            )
        ).scalar_one_or_none()
        if profile is None or profile.sharing_policy != "public":
            raise ApiError(404, "ARTIST_NOT_FOUND", "Public artist profile not found.")
        tracks = list(
            session.execute(
                select(ArtistSong, Asset)
                .join(Asset, Asset.id == ArtistSong.asset_id)
                .where(
                    ArtistSong.profile_id == profile.id,
                    ArtistSong.owner_id == profile.owner_id,
                    Asset.shared.is_(True),
                    Asset.deleted_at.is_(None),
                    Asset.mime.like("audio/%"),
                )
                .order_by(ArtistSong.position, ArtistSong.created_at)
            ).all()
        )
    from datetime import timedelta

    from ..models import utcnow

    expiry = utcnow() + timedelta(hours=24)
    items = [
        {
            "asset_id": a.id,
            "title": a.title,
            "slug": a.slug,
            "url": f"/api/v1/artifacts/{a.id}/content?token={make_token(settings.secret_key, a.id, expiry)}",
        }
        for _, a in tracks
    ]
    return JSONResponse(
        {
            "profile_id": profile.id,
            "name": profile.name,
            "slug": profile.slug,
            "bio": profile.bio,
            "avatar_url": f"/api/v1/artist-profiles/{profile.id}/avatar" if profile.avatar_key else None,
            "tracks": items,
        }
    )
