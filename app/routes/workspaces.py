"""Workspaces: customer-facing song collections (M17).

A workspace groups saved song recipes (title, lyrics, style tags, seed, duration)
so a track can be reproduced, remixed, rerolled or rewritten later.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import func, select

from ..deps import owner_from_request
from ..errors import ApiError
from ..models import ArtistProfile, Asset, Job, User, VoiceAdapter, Workspace, WorkspaceSong, new_uuid
from ..schemas import StrictModel

router = APIRouter(tags=["workspaces"])

DEFAULT_WORKSPACE_NAME = "My Default Space"


class WorkspaceCreate(StrictModel):
    name: str = Field(min_length=1, max_length=200)


class WorkspaceMove(StrictModel):
    asset_ids: list[str] = Field(min_length=1)
    workspace_id: str | None = Field(default=None, max_length=36)  # None -> default space


class WorkspaceSongCreate(StrictModel):
    asset_id: str | None = Field(default=None, max_length=36)
    job_id: str | None = Field(default=None, max_length=36)
    title: str = Field(default="Untitled", max_length=200)


class ActiveWorkspaceSet(StrictModel):
    workspace_id: str | None = Field(default=None, max_length=36)


class WorkspaceArtistSet(StrictModel):
    artist_profile_id: str | None = Field(default=None, max_length=36)


def ensure_default_workspace(session, owner_id: str) -> Workspace:
    """Return the owner's always-present 'My Default Space' (create if missing)."""
    ws = session.execute(
        select(Workspace).where(
            Workspace.owner_id == owner_id, Workspace.is_default, Workspace.deleted_at.is_(None)
        )
    ).scalars().first()
    if ws is None:
        ws = Workspace(id=new_uuid(), owner_id=owner_id, name=DEFAULT_WORKSPACE_NAME, is_default=True)
        session.add(ws)
        session.commit()
    return ws


def _get_owned(session, workspace_id: str, owner_id: str) -> Workspace:
    ws = session.get(Workspace, workspace_id)
    if ws is None or ws.owner_id != owner_id or ws.deleted_at is not None:
        raise ApiError(404, "WORKSPACE_NOT_FOUND", "Workspace not found.")
    return ws


def _ws_json(ws: Workspace, song_count: int = 0, asset_count: int = 0, artist: dict | None = None) -> dict:
    return {
        "workspace_id": ws.id,
        "name": ws.name,
        "is_default": bool(ws.is_default),
        "artist_profile_id": ws.artist_profile_id,
        "artist": artist,
        "song_count": song_count,
        "asset_count": asset_count,
        "created_at": ws.created_at.isoformat() if ws.created_at else None,
    }


def _workspace_artist_map(session, workspaces) -> dict[str, dict]:
    """Attached-artist details (UAIS voice state) per workspace."""
    profile_ids = sorted({ws.artist_profile_id for ws in workspaces if ws.artist_profile_id})
    if not profile_ids:
        return {}
    profiles = {
        p.id: p
        for p in session.execute(select(ArtistProfile).where(ArtistProfile.id.in_(profile_ids))).scalars()
    }
    adapters: dict[str, list] = {}
    for a in session.execute(
        select(VoiceAdapter).where(
            VoiceAdapter.artist_profile_id.in_(profile_ids),
            VoiceAdapter.state.in_(("validated", "ready", "stale")),
        ).order_by(VoiceAdapter.created_at.desc())
    ).scalars():
        adapters.setdefault(a.artist_profile_id, []).append(a)
    rank = {"validated": 0, "ready": 1, "stale": 2}
    out: dict[str, dict] = {}
    for ws in workspaces:
        profile = profiles.get(ws.artist_profile_id or "")
        if profile is None:
            continue
        best = sorted(adapters.get(profile.id, []), key=lambda a: rank.get(a.state, 9))[0] if adapters.get(profile.id) else None
        out[ws.id] = {
            "profile_id": profile.id,
            "name": profile.name,
            "slug": profile.slug,
            "is_main": bool(profile.is_main),
            "sharing_policy": profile.sharing_policy,
            "default_voice_profile_id": profile.default_voice_profile_id,
            "default_adapter_id": best.id if best else None,
            "adapter_model_selection": best.model_selection if best else None,
            "adapter_state": best.state if best else None,
            "applicable": best is not None,
        }
    return out


def _song_json(song: WorkspaceSong) -> dict:
    return {
        "song_id": song.id,
        "workspace_id": song.workspace_id,
        "title": song.title,
        "description": song.description,
        "lyrics": song.lyrics,
        "style_tags": song.style_tags or [],
        "seed": song.seed,
        "duration_seconds": song.duration_seconds,
        "instrumental": song.instrumental,
        "asset_id": song.asset_id,
        "job_id": song.job_id,
        "created_at": song.created_at.isoformat() if song.created_at else None,
    }


@router.get("/workspaces")
def list_workspaces(request: Request, owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    with request.app.state.db.session() as session:
        ensure_default_workspace(session, owner_id)
        rows = list(
            session.execute(
                select(Workspace)
                .where(Workspace.owner_id == owner_id, Workspace.deleted_at.is_(None))
                .order_by(Workspace.is_default.desc(), Workspace.created_at.desc())
            ).scalars()
        )
        song_counts: dict[str, int] = {}
        for ws_id, in session.execute(
            select(WorkspaceSong.workspace_id).where(WorkspaceSong.owner_id == owner_id)
        ).all():
            song_counts[ws_id] = song_counts.get(ws_id, 0) + 1
        asset_counts = {ws_id: cnt for ws_id, cnt in session.execute(
            select(Asset.workspace_id, func.count())
            .where(Asset.owner_id == owner_id, Asset.deleted_at.is_(None), Asset.workspace_id.isnot(None))
            .group_by(Asset.workspace_id)
        ).all()}
        default = next((w for w in rows if w.is_default), None)
        unfiled = 0
        if default is not None:
            unfiled = session.execute(
                select(func.count()).where(
                    Asset.owner_id == owner_id, Asset.deleted_at.is_(None), Asset.workspace_id.is_(None)
                )
            ).scalar() or 0
            asset_counts[default.id] = asset_counts.get(default.id, 0) + unfiled
        artist_map = _workspace_artist_map(session, rows)
    return JSONResponse(
        {
            "workspaces": [
                _ws_json(ws, song_counts.get(ws.id, 0), asset_counts.get(ws.id, 0), artist_map.get(ws.id))
                for ws in rows
            ]
        }
    )


@router.post("/workspaces", status_code=201)
def create_workspace(payload: WorkspaceCreate, request: Request, owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    name = payload.name.strip()
    if not name:
        raise ApiError(422, "WORKSPACE_NAME_REQUIRED", "Workspace name is required.")
    with request.app.state.db.session() as session:
        if name == DEFAULT_WORKSPACE_NAME:
            raise ApiError(409, "WORKSPACE_NAME_RESERVED", "'My Default Space' is reserved.")
        ws = Workspace(id=new_uuid(), owner_id=owner_id, name=name)
        session.add(ws)
        session.commit()
        return JSONResponse(status_code=201, content=_ws_json(ws))


@router.get("/workspaces/active")
def get_active_workspace(request: Request, owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    """Effective workspace for routing new generations (the account's pick, else default)."""
    with request.app.state.db.session() as session:
        user = session.get(User, owner_id[4:]) if owner_id.startswith("usr_") else None
        active = user.active_workspace_id if user else None
        if active is not None:
            ws = session.get(Workspace, active)
            if ws is None or ws.deleted_at is not None or ws.owner_id != owner_id:
                active = None
        default = ensure_default_workspace(session, owner_id)
        return JSONResponse({"workspace_id": active or default.id, "is_default": active is None})


@router.post("/workspaces/active")
def set_active_workspace(
    payload: ActiveWorkspaceSet, request: Request, owner_id: str = Depends(owner_from_request)
) -> JSONResponse:
    """Persist the account's active workspace (None -> My Default Space)."""
    with request.app.state.db.session() as session:
        if not owner_id.startswith("usr_"):
            raise ApiError(400, "ACCOUNT_REQUIRED", "Active workspace requires a site account.")
        user = session.get(User, owner_id[4:])
        if user is None or user.state != "active":
            raise ApiError(403, "USER_DISABLED", "Account is missing or disabled.")
        if payload.workspace_id is None:
            ws = ensure_default_workspace(session, owner_id)
            user.active_workspace_id = None
        else:
            ws = _get_owned(session, payload.workspace_id, owner_id)
            user.active_workspace_id = ws.id
        session.commit()
        return JSONResponse({"workspace_id": ws.id})


@router.get("/workspaces/{workspace_id}")
def get_workspace(workspace_id: str, request: Request, owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    with request.app.state.db.session() as session:
        ws = _get_owned(session, workspace_id, owner_id)
        return JSONResponse(_ws_json(ws))


@router.patch("/workspaces/{workspace_id}")
def rename_workspace(workspace_id: str, payload: WorkspaceCreate, request: Request, owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    name = payload.name.strip()
    if not name:
        raise ApiError(422, "WORKSPACE_NAME_REQUIRED", "Workspace name is required.")
    with request.app.state.db.session() as session:
        ws = _get_owned(session, workspace_id, owner_id)
        if ws.is_default:
            raise ApiError(409, "WORKSPACE_DEFAULT_LOCKED", "The default space cannot be renamed.")
        if name == DEFAULT_WORKSPACE_NAME:
            raise ApiError(409, "WORKSPACE_NAME_RESERVED", "'My Default Space' is reserved.")
        ws.name = name
        session.commit()
        return JSONResponse(_ws_json(ws))


@router.patch("/workspaces/{workspace_id}/artist")
def set_workspace_artist(
    workspace_id: str,
    payload: WorkspaceArtistSet,
    request: Request,
    owner_id: str = Depends(owner_from_request),
) -> JSONResponse:
    """Attach (or detach with null) one of the owner's artist profiles to a workspace."""
    with request.app.state.db.session() as session:
        ws = _get_owned(session, workspace_id, owner_id)
        if payload.artist_profile_id is None:
            ws.artist_profile_id = None
            session.commit()
            return JSONResponse(_ws_json(ws))
        profile = session.get(ArtistProfile, payload.artist_profile_id)
        if profile is None or profile.owner_id != owner_id or profile.deleted_at is not None:
            raise ApiError(404, "PROFILE_NOT_FOUND", "Artist profile not found.")
        ws.artist_profile_id = profile.id
        session.commit()
        artist_map = _workspace_artist_map(session, [ws])
        return JSONResponse(_ws_json(ws, artist=artist_map.get(ws.id)))


@router.post("/workspaces/move")
def move_assets(payload: WorkspaceMove, request: Request, owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    """Assign the given owned assets to a workspace (None -> the default space)."""
    with request.app.state.db.session() as session:
        if payload.workspace_id is None:
            target = ensure_default_workspace(session, owner_id)
            target_id = target.id
        else:
            target = _get_owned(session, payload.workspace_id, owner_id)
            target_id = target.id
        moved = 0
        for aid in payload.asset_ids[:500]:
            asset = session.get(Asset, aid)
            if asset is None or asset.owner_id != owner_id or asset.deleted_at is not None:
                continue
            asset.workspace_id = target_id
            moved += 1
        session.commit()
    return JSONResponse({"moved": moved, "workspace_id": target_id})


@router.delete("/workspaces/{workspace_id}", status_code=204)
def delete_workspace(workspace_id: str, request: Request, owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    from ..models import utcnow

    with request.app.state.db.session() as session:
        ws = _get_owned(session, workspace_id, owner_id)
        if ws.is_default:
            raise ApiError(409, "WORKSPACE_DEFAULT_UNDELETABLE", "The default space cannot be deleted.")
        default = ensure_default_workspace(session, owner_id)
        # Reassign members back to the default space rather than deleting audio.
        for asset in session.execute(
            select(Asset).where(Asset.owner_id == owner_id, Asset.workspace_id == ws.id)
        ).scalars():
            asset.workspace_id = default.id
        for song in session.execute(
            select(WorkspaceSong).where(WorkspaceSong.owner_id == owner_id, WorkspaceSong.workspace_id == ws.id)
        ).scalars():
            song.workspace_id = default.id
        ws.deleted_at = utcnow()
        session.commit()
    return JSONResponse(status_code=204, content=None)


@router.get("/workspaces/{workspace_id}/songs")
def list_songs(workspace_id: str, request: Request, owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    with request.app.state.db.session() as session:
        _get_owned(session, workspace_id, owner_id)
        rows = list(
            session.execute(
                select(WorkspaceSong)
                .where(WorkspaceSong.workspace_id == workspace_id, WorkspaceSong.owner_id == owner_id)
                .order_by(WorkspaceSong.created_at.desc())
            ).scalars()
        )
    return JSONResponse({"songs": [_song_json(s) for s in rows]})


@router.post("/workspaces/{workspace_id}/songs", status_code=201)
def add_song(workspace_id: str, payload: WorkspaceSongCreate, request: Request, owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    with request.app.state.db.session() as session:
        _get_owned(session, workspace_id, owner_id)
        job: Job | None = None
        asset: Asset | None = None
        if payload.job_id:
            job = session.execute(select(Job).where(Job.id == payload.job_id)).scalar_one_or_none()
            if job is None or job.owner_id != owner_id:
                raise ApiError(404, "JOB_NOT_FOUND", "Job not found.")
        if payload.asset_id:
            asset = session.get(Asset, payload.asset_id)
            if asset is None or asset.owner_id != owner_id:
                raise ApiError(404, "ASSET_NOT_FOUND", "Asset not found.")
            if job is None and asset.job_id:
                job = session.get(Job, asset.job_id)
        req = (job.request_json or {}) if job else {}
        tags = [t.strip() for t in str(req.get("music_description", "")).split(",") if t.strip()]
        song = WorkspaceSong(
            id=new_uuid(),
            workspace_id=workspace_id,
            owner_id=owner_id,
            title=(payload.title if payload.title != "Untitled" else (asset.title if asset and asset.title else "Untitled"))[:200],
            description=req.get("music_description"),
            lyrics=job.lyrics if job else None,
            style_tags=tags,
            seed=req.get("seed"),
            duration_seconds=req.get("duration_seconds"),
            instrumental=bool(req.get("instrumental")),
            asset_id=payload.asset_id or (asset.id if asset else None),
            job_id=job.id if job else None,
        )
        session.add(song)
        # Keep real membership in sync: saving a track into a workspace files it there.
        if asset is not None:
            asset.workspace_id = workspace_id
        session.commit()
        return JSONResponse(status_code=201, content=_song_json(song))


@router.delete("/workspaces/{workspace_id}/songs/{song_id}", status_code=204)
def remove_song(workspace_id: str, song_id: str, request: Request, owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    with request.app.state.db.session() as session:
        song = session.get(WorkspaceSong, song_id)
        if song is None or song.workspace_id != workspace_id or song.owner_id != owner_id:
            raise ApiError(404, "SONG_NOT_FOUND", "Song not found in workspace.")
        session.delete(song)
        session.commit()
    return JSONResponse(status_code=204, content=None)
