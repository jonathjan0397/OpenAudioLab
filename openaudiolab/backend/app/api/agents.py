import hashlib
import os
import tempfile
import uuid
from typing import Optional

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile

from app.core.config import settings
from app.core.enums import AssetType
from app.storage.service import StorageService
from app.workers.schemas import (
    HeartbeatRequest,
    StageUpdateRequest,
    AgentRegistrationRequest,
)
from app.workers.service import AgentService

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("")
async def list_agents():
    return AgentService.list_agents()


@router.post("/register")
async def register_agent(request: AgentRegistrationRequest):
    return AgentService.register_agent(request)


@router.post("/heartbeat")
async def agent_heartbeat(
    request: HeartbeatRequest,
    x_agent_token: str = Header(..., alias="X-Agent-Token"),
):
    return AgentService.process_heartbeat(request, x_agent_token)


@router.post("/request-job")
async def request_job(
    agent_id: str,
    x_agent_token: str = Header(..., alias="X-Agent-Token"),
):
    return AgentService.request_job(agent_id, x_agent_token)


@router.post("/jobs/{job_id}/stage-update")
async def update_stage(
    job_id: str,
    request: StageUpdateRequest,
    x_agent_token: str = Header(..., alias="X-Agent-Token"),
):
    from app.jobs.state_machine import StateMachine
    from app.core.enums import StageStatus, JobStatus
    from app.db.session import SessionLocal
    from app.db.models import JobStage, GenerationJob

    db = SessionLocal()
    try:
        stage = db.query(JobStage).filter(
            JobStage.job_id == job_id,
            JobStage.stage_name == request.stage_name,
        ).first()
        if not stage:
            raise HTTPException(status_code=404, detail="Stage not found")

        StateMachine.transition_stage(
            stage.id,
            StageStatus(request.status),
            metadata=request.metadata,
            error_message=request.error_message,
        )

        if request.status == "completed":
            all_stages = db.query(JobStage).filter(JobStage.job_id == job_id).all()
            all_completed = all(s.status in ("completed", "skipped") for s in all_stages)
            if all_completed:
                StateMachine.transition_job(job_id, JobStatus.COMPLETED)
            else:
                StateMachine.transition_job(job_id, JobStatus.STAGE_COMPLETED)
                StateMachine.transition_job(job_id, JobStatus.RUNNING)

        return {"accepted": True}
    finally:
        db.close()


@router.post("/jobs/{job_id}/complete")
async def complete_job(
    job_id: str,
    x_agent_token: str = Header(..., alias="X-Agent-Token"),
):
    from app.jobs.state_machine import StateMachine
    from app.core.enums import JobStatus

    StateMachine.transition_job(job_id, JobStatus.COMPLETED)
    return {"accepted": True}


@router.post("/jobs/{job_id}/fail")
async def fail_job(
    job_id: str,
    error_message: str = "Agent reported failure",
    x_agent_token: str = Header(..., alias="X-Agent-Token"),
):
    from app.jobs.state_machine import StateMachine
    from app.core.enums import JobStatus

    StateMachine.transition_job(job_id, JobStatus.FAILED, error_message=error_message)
    return {"accepted": True}


_MIME_GUESS = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".zip": "application/zip",
    ".json": "application/json",
    ".txt": "text/plain",
    ".log": "text/plain",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".csv": "text/csv",
    ".md": "text/markdown",
    ".html": "text/html",
    ".pdf": "application/pdf",
}


def _guess_mime(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return _MIME_GUESS.get(f".{ext}", "application/octet-stream")


@router.post("/jobs/{job_id}/artifacts")
async def upload_artifact(
    job_id: str,
    file: UploadFile = File(...),
    asset_type: str = Form(...),
    filename: Optional[str] = Form(None),
    x_agent_token: str = Header(..., alias="X-Agent-Token"),
):
    from app.db.models import AgentNode, GenerationJob, StorageAsset
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        job = db.query(GenerationJob).filter(GenerationJob.id == job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        agent = db.query(AgentNode).filter(
            AgentNode.agent_api_token == x_agent_token,
        ).first()
        if not agent or str(agent.id) != str(job.assigned_agent_id):
            raise HTTPException(status_code=403, detail="Agent not assigned to this job")

        content = await file.read()
        safe_name = filename or file.filename or f"{asset_type}_{uuid.uuid4().hex[:8]}"
        remote_key = StorageService.get_job_storage_key(job_id, f"{asset_type}/{safe_name}")

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=safe_name)
        try:
            tmp.write(content)
            tmp.close()
            stored = StorageService.upload_file(tmp.name, remote_key)
        finally:
            os.unlink(tmp.name)

        if not stored:
            raise HTTPException(status_code=500, detail="Storage upload failed")

        mime = _guess_mime(safe_name)
        sha256 = hashlib.sha256(content).hexdigest()
        asset = StorageAsset(
            job_id=job_id,
            asset_type=asset_type,
            storage_provider=settings.STORAGE_PROVIDER,
            storage_key=remote_key,
            filename=safe_name,
            mime_type=mime,
            size_bytes=len(content),
            sha256=sha256,
            expires_at=StorageService.get_retention_expires_at(job.storage_retention_days),
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)

        return {
            "accepted": True,
            "asset_id": asset.id,
            "storage_key": remote_key,
        }
    finally:
        db.close()
