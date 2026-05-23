from fastapi import APIRouter, Header, HTTPException

from app.workers.schemas import (
    HeartbeatRequest,
    StageUpdateRequest,
    WorkerRegistrationRequest,
)
from app.workers.service import WorkerService

router = APIRouter(prefix="/api/workers", tags=["workers"])


@router.get("")
async def list_workers():
    return WorkerService.list_workers()


@router.post("/register")
async def register_worker(request: WorkerRegistrationRequest):
    return WorkerService.register_worker(request)


@router.post("/heartbeat")
async def worker_heartbeat(
    request: HeartbeatRequest,
    x_worker_token: str = Header(..., alias="X-Worker-Token"),
):
    return WorkerService.process_heartbeat(request, x_worker_token)


@router.post("/request-job")
async def request_job(
    worker_id: str,
    x_worker_token: str = Header(..., alias="X-Worker-Token"),
):
    return WorkerService.request_job(worker_id, x_worker_token)


@router.post("/jobs/{job_id}/stage-update")
async def update_stage(
    job_id: str,
    request: StageUpdateRequest,
    x_worker_token: str = Header(..., alias="X-Worker-Token"),
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
    x_worker_token: str = Header(..., alias="X-Worker-Token"),
):
    from app.jobs.state_machine import StateMachine
    from app.core.enums import JobStatus

    StateMachine.transition_job(job_id, JobStatus.COMPLETED)
    return {"accepted": True}


@router.post("/jobs/{job_id}/fail")
async def fail_job(
    job_id: str,
    error_message: str = "Worker reported failure",
    x_worker_token: str = Header(..., alias="X-Worker-Token"),
):
    from app.jobs.state_machine import StateMachine
    from app.core.enums import JobStatus

    StateMachine.transition_job(job_id, JobStatus.FAILED, error_message=error_message)
    return {"accepted": True}
