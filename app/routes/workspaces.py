"""Workspaces: customer-facing song collections (M17).

A workspace groups saved song recipes (title, lyrics, style tags, seed, duration)
so a track can be reproduced, remixed, rerolled or rewritten later.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import select

from ..deps import owner_from_request
from ..errors import ApiError
from ..models import Asset, Job, Workspace, WorkspaceSong, new_uuid
from ..schemas import StrictModel

router = APIRouter(tags=["workspaces"])


class WorkspaceCreate(StrictModel):
    name: str = Field(min_length=1, max_length=200)


class WorkspaceSongCreate(StrictModel):
    asset_id: str | None = Field(default=None, max_length=36)
    job_id: str | None = Field(default=None, max_length=36)
    title: str = Field(default="Untitled", max_length=200)


def _get_owned(session, workspace_id: str, owner_id: str) -> Workspace:
    ws = session.get(Workspace, workspace_id)
    if ws is None or ws.owner_id != owner_id or ws.deleted_at is not None:
        raise ApiError(404, "WORKSPACE_NOT_FOUND", "Workspace not found.")
    return ws


def _ws_json(ws: Workspace, song_count: int = 0) -> dict:
    return {
        "workspace_id": ws.id,
        "name": ws.name,
        "song_count": song_count,
        "created_at": ws.created_at.isoformat() if ws.created_at else None,
    }


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
        rows = list(
            session.execute(
                select(Workspace)
                .where(Workspace.owner_id == owner_id, Workspace.deleted_at.is_(None))
                .order_by(Workspace.created_at.desc())
            ).scalars()
        )
        counts: dict[str, int] = {}
        for ws_id, in session.execute(
            select(WorkspaceSong.workspace_id).where(WorkspaceSong.owner_id == owner_id)
        ).all():
            counts[ws_id] = counts.get(ws_id, 0) + 1
    return JSONResponse({"workspaces": [_ws_json(ws, counts.get(ws.id, 0)) for ws in rows]})


@router.post("/workspaces", status_code=201)
def create_workspace(payload: WorkspaceCreate, request: Request, owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    with request.app.state.db.session() as session:
        ws = Workspace(id=new_uuid(), owner_id=owner_id, name=payload.name)
        session.add(ws)
        session.commit()
        return JSONResponse(status_code=201, content=_ws_json(ws))


@router.get("/workspaces/{workspace_id}")
def get_workspace(workspace_id: str, request: Request, owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    with request.app.state.db.session() as session:
        ws = _get_owned(session, workspace_id, owner_id)
        return JSONResponse(_ws_json(ws))


@router.patch("/workspaces/{workspace_id}")
def rename_workspace(workspace_id: str, payload: WorkspaceCreate, request: Request, owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    with request.app.state.db.session() as session:
        ws = _get_owned(session, workspace_id, owner_id)
        ws.name = payload.name
        session.commit()
        return JSONResponse(_ws_json(ws))


@router.delete("/workspaces/{workspace_id}", status_code=204)
def delete_workspace(workspace_id: str, request: Request, owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    from ..models import utcnow

    with request.app.state.db.session() as session:
        ws = _get_owned(session, workspace_id, owner_id)
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
