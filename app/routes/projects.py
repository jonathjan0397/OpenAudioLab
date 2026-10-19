"""Projects, immutable versions and restore pointers (milestone 4).

Optimistic concurrency: project rows carry an integer ETag version. Edits
(PATCH/restore) require If-Match; a mismatch is 412, a missing precondition
is 428. Versions are immutable once created.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..deps import owner_from_request
from ..errors import ApiError
from ..models import Asset, Job, Project, ProjectVersion, new_uuid, utcnow
from ..schemas import (
    ProjectCreate,
    ProjectPage,
    ProjectPatch,
    ProjectResponse,
    RestoreRequest,
    VersionCreate,
    VersionPage,
    VersionResponse,
)

router = APIRouter(tags=["projects"])


def _etag(project: Project) -> str:
    return f'"{project.etag_version}"'


def _response(project: Project) -> ProjectResponse:
    return ProjectResponse(
        project_id=project.id,
        name=project.name,
        active_version_id=project.active_version_id,
        etag=_etag(project),
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def _get_owned_project(session: Session, project_id: str, owner_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None or project.owner_id != owner_id or project.deleted_at is not None:
        raise ApiError(404, "PROJECT_NOT_FOUND", "Project not found.")
    return project


def _require_if_match(request: Request, project: Project) -> None:
    header = request.headers.get("If-Match")
    if header is None:
        raise ApiError(428, "PRECONDITION_REQUIRED", "PATCH and restore require an If-Match header.")
    if header.strip().strip('"') != str(project.etag_version):
        raise ApiError(
            412,
            "ETAG_MISMATCH",
            "If-Match does not match the current project revision.",
            {"current_etag": _etag(project)},
        )


def _version_response(version: ProjectVersion) -> VersionResponse:
    return VersionResponse(
        version_id=version.id,
        project_id=version.project_id,
        kind=version.kind,
        label=version.label,
        source_job_id=version.source_job_id,
        source_asset_id=version.source_asset_id,
        parent_version_id=version.parent_version_id,
        manifest=version.manifest,
        created_at=version.created_at,
    )


@router.post("/projects", status_code=201, response_model=ProjectResponse)
def create_project(
    payload: ProjectCreate,
    request: Request,
    owner_id: str = Depends(owner_from_request),
) -> JSONResponse:
    with request.app.state.db.session() as session:
        project = Project(id=new_uuid(), owner_id=owner_id, name=payload.name)
        session.add(project)
        session.commit()
        body = _response(project)
    return JSONResponse(status_code=201, content=body.model_dump(mode="json"), headers={"ETag": body.etag})


@router.get("/projects", response_model=ProjectPage)
def list_projects(
    request: Request,
    owner_id: str = Depends(owner_from_request),
) -> ProjectPage:
    with request.app.state.db.session() as session:
        rows = list(
            session.execute(
                select(Project)
                .where(Project.owner_id == owner_id, Project.deleted_at.is_(None))
                .order_by(Project.created_at.desc())
            ).scalars()
        )
    return ProjectPage(projects=[_response(project) for project in rows])


@router.get("/projects/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: str,
    request: Request,
    owner_id: str = Depends(owner_from_request),
) -> JSONResponse:
    with request.app.state.db.session() as session:
        project = _get_owned_project(session, project_id, owner_id)
        body = _response(project)
    return JSONResponse(status_code=200, content=body.model_dump(mode="json"), headers={"ETag": body.etag})


@router.patch("/projects/{project_id}", response_model=ProjectResponse)
def patch_project(
    project_id: str,
    payload: ProjectPatch,
    request: Request,
    owner_id: str = Depends(owner_from_request),
) -> JSONResponse:
    with request.app.state.db.session() as session:
        project = _get_owned_project(session, project_id, owner_id)
        _require_if_match(request, project)
        if payload.name is not None:
            project.name = payload.name
        if payload.active_version_id is not None:
            version = session.get(ProjectVersion, payload.active_version_id)
            if version is None or version.project_id != project.id or version.owner_id != owner_id:
                raise ApiError(422, "VERSION_NOT_FOUND", "Version does not belong to this project.")
            project.active_version_id = version.id
        project.etag_version += 1
        session.commit()
        body = _response(project)
    return JSONResponse(status_code=200, content=body.model_dump(mode="json"), headers={"ETag": body.etag})


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(
    project_id: str,
    request: Request,
    owner_id: str = Depends(owner_from_request),
) -> Response:
    with request.app.state.db.session() as session:
        project = _get_owned_project(session, project_id, owner_id)
        project.deleted_at = utcnow()
        session.commit()
    return Response(status_code=204)


@router.post("/projects/{project_id}/versions", status_code=201, response_model=VersionResponse)
def create_version(
    project_id: str,
    payload: VersionCreate,
    request: Request,
    owner_id: str = Depends(owner_from_request),
) -> VersionResponse:
    if (payload.source_job_id is None) == (payload.source_asset_id is None):
        raise ApiError(422, "VERSION_SOURCE_AMBIGUOUS", "Provide exactly one of source_job_id or source_asset_id.")
    with request.app.state.db.session() as session:
        project = _get_owned_project(session, project_id, owner_id)
        asset: Asset | None = None
        job: Job | None = None
        if payload.source_job_id is not None:
            job = session.execute(select(Job).where(Job.id == payload.source_job_id)).scalar_one_or_none()
            if job is None or job.owner_id != owner_id:
                raise ApiError(404, "JOB_NOT_FOUND", "Job not found.")
            if job.status != "succeeded":
                raise ApiError(409, "STATE_CONFLICT", "Only succeeded jobs can become versions.")
            asset = session.execute(
                select(Asset).where(Asset.job_id == job.id, Asset.role == "mix_wav", Asset.deleted_at.is_(None))
            ).scalars().first()
            kind = "generated"
        else:
            asset = session.get(Asset, payload.source_asset_id or "")
            if asset is None or asset.owner_id != owner_id:
                raise ApiError(404, "ASSET_NOT_FOUND", "Asset not found.")
            kind = "uploaded"
        if asset is None or asset.deleted_at is not None:
            raise ApiError(422, "VERSION_SOURCE_UNAVAILABLE", "The source has no usable audio asset.")
        manifest = {
            "origin": kind,
            "asset_id": asset.id,
            "sha256": asset.sha256,
            "mime": asset.mime,
            "bytes": asset.bytes,
            "sample_rate": asset.sample_rate,
            "channels": asset.channels,
            "duration_seconds": asset.duration_seconds,
            "synthetic_test_audio": asset.synthetic,
        }
        if job is not None:
            manifest["model_id"] = job.model_id
            manifest["model_revision"] = job.model_revision
            manifest["lyrics_sha256"] = job.lyrics_sha256
        version = ProjectVersion(
            id=new_uuid(),
            project_id=project.id,
            owner_id=owner_id,
            kind=kind,
            label=payload.label,
            source_job_id=job.id if job else None,
            source_asset_id=asset.id,
            parent_version_id=project.active_version_id,
            manifest=manifest,
        )
        session.add(version)
        project.active_version_id = version.id
        project.etag_version += 1
        session.commit()
        return _version_response(version)


@router.get("/projects/{project_id}/versions", response_model=VersionPage)
def list_versions(
    project_id: str,
    request: Request,
    owner_id: str = Depends(owner_from_request),
) -> VersionPage:
    with request.app.state.db.session() as session:
        project = _get_owned_project(session, project_id, owner_id)
        rows = list(
            session.execute(
                select(ProjectVersion)
                .where(ProjectVersion.project_id == project.id)
                .order_by(ProjectVersion.created_at.desc())
            ).scalars()
        )
    return VersionPage(versions=[_version_response(version) for version in rows])


@router.get("/projects/{project_id}/versions/{version_id}", response_model=VersionResponse)
def get_version(
    project_id: str,
    version_id: str,
    request: Request,
    owner_id: str = Depends(owner_from_request),
) -> VersionResponse:
    with request.app.state.db.session() as session:
        project = _get_owned_project(session, project_id, owner_id)
        version = session.get(ProjectVersion, version_id)
        if version is None or version.project_id != project.id or version.owner_id != owner_id:
            raise ApiError(404, "VERSION_NOT_FOUND", "Version not found.")
        return _version_response(version)


@router.post("/projects/{project_id}/restore", response_model=ProjectResponse)
def restore_project(
    project_id: str,
    payload: RestoreRequest,
    request: Request,
    owner_id: str = Depends(owner_from_request),
) -> JSONResponse:
    with request.app.state.db.session() as session:
        project = _get_owned_project(session, project_id, owner_id)
        _require_if_match(request, project)
        version = session.get(ProjectVersion, payload.version_id)
        if version is None or version.project_id != project.id or version.owner_id != owner_id:
            raise ApiError(404, "VERSION_NOT_FOUND", "Version not found.")
        project.active_version_id = version.id
        project.etag_version += 1
        session.commit()
        body = _response(project)
    return JSONResponse(status_code=200, content=body.model_dump(mode="json"), headers={"ETag": body.etag})
