from fastapi import APIRouter, Header, HTTPException

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
