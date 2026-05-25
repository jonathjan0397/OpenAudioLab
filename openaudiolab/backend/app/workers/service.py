from datetime import datetime, timezone
from typing import Optional

from app.core.config import settings
from app.core.security import generate_secure_token
from app.db.models import AgentHeartbeat, AgentNode
from app.db.session import SessionLocal
from app.workers.schemas import (
    HeartbeatRequest,
    HeartbeatResponse,
    JobRequestResponse,
    AgentRegistrationRequest,
    AgentRegistrationResponse,
    AgentResponse,
)


class AgentService:
    @staticmethod
    def register_agent(request: AgentRegistrationRequest) -> AgentRegistrationResponse:
        if request.registration_token != settings.AGENT_REGISTRATION_TOKEN:
            return AgentRegistrationResponse(
                accepted=False,
                message="Invalid registration token",
            )

        db = SessionLocal()
        try:
            existing = db.query(AgentNode).filter(AgentNode.agent_name == request.agent_name).first()
            if existing:
                agent = existing
                agent.status = "registering"
                agent.gpu_available = request.gpu.get("available", False)
                agent.gpu_name = request.gpu.get("name")
                agent.vram_gb = request.gpu.get("vram_gb", 0)
                agent.cuda_available = request.gpu.get("cuda_available", False)
                agent.capabilities_json = request.capabilities
                agent.model_packs_json = request.model_packs
                agent.container_version = request.container_version
                agent.hostname = request.hostname
                agent.agent_mode = request.agent_mode
            else:
                agent_api_token = f"agent_{generate_secure_token(48)}"
                agent = AgentNode(
                    agent_name=request.agent_name,
                    status="registering",
                    agent_mode=request.agent_mode,
                    hostname=request.hostname,
                    gpu_available=request.gpu.get("available", False),
                    gpu_name=request.gpu.get("name"),
                    vram_gb=request.gpu.get("vram_gb", 0),
                    cuda_available=request.gpu.get("cuda_available", False),
                    capabilities_json=request.capabilities,
                    model_packs_json=request.model_packs,
                    container_version=request.container_version,
                    agent_api_token=agent_api_token,
                )
                db.add(agent)

            db.commit()
            db.refresh(agent)

            agent.status = "idle"
            db.commit()

            return AgentRegistrationResponse(
                accepted=True,
                agent_id=agent.id,
                agent_api_token=agent.agent_api_token,
                message="Agent registered successfully",
            )
        finally:
            db.close()

    @staticmethod
    def process_heartbeat(request: HeartbeatRequest, agent_api_token: str) -> HeartbeatResponse:
        db = SessionLocal()
        try:
            agent = db.query(AgentNode).filter(
                AgentNode.id == request.agent_id,
                AgentNode.agent_api_token == agent_api_token,
            ).first()

            if not agent:
                return HeartbeatResponse(accepted=False)

            agent.status = request.status
            agent.last_heartbeat_at = datetime.now(timezone.utc)
            agent.draining = request.draining
            agent.container_version = request.container_version

            heartbeat = AgentHeartbeat(
                agent_id=agent.id,
                status=request.status,
                active_job_id=request.active_job_id,
                gpu_utilization=request.gpu_utilization,
                vram_used_gb=request.vram_used_gb,
                disk_free_gb=request.disk_free_gb,
                container_version=request.container_version,
                draining=request.draining,
            )
            db.add(heartbeat)
            db.commit()

            update_required = request.container_version != settings.AGENT_VERSION
            drain_requested = agent.draining

            return HeartbeatResponse(
                accepted=True,
                update_required=update_required,
                drain_requested=drain_requested,
            )
        finally:
            db.close()

    @staticmethod
    def request_job(agent_id: str, agent_api_token: str) -> JobRequestResponse:
        db = SessionLocal()
        try:
            from app.db.models import GenerationJob
            from app.jobs.queue import JobQueue
            from app.core.enums import JobStatus

            agent = db.query(AgentNode).filter(
                AgentNode.id == agent_id,
                AgentNode.agent_api_token == agent_api_token,
            ).first()

            if not agent or agent.status in ("offline", "draining"):
                return JobRequestResponse(job_available=False)

            job_id = JobQueue.dequeue_job()
            if not job_id:
                return JobRequestResponse(job_available=False)

            job = db.query(GenerationJob).filter(GenerationJob.id == job_id).first()
            if not job:
                return JobRequestResponse(job_available=False)

            job.status = JobStatus.ASSIGNED.value
            job.assigned_agent_id = agent_id
            job.updated_at = datetime.now(timezone.utc)
            db.commit()

            return JobRequestResponse(
                job_available=True,
                job={
                    "job_id": job.id,
                    "pipeline": [s.stage_name for s in job.stages],
                    "request": {
                        "prompt": job.prompt,
                        "genre": job.genre,
                        "mood": job.mood,
                        "lyrics_mode": job.lyrics_mode,
                        "provided_lyrics": job.provided_lyrics,
                        "instrumental": job.instrumental,
                        "duration_seconds": job.duration_seconds,
                        "vocal_mode": job.vocal_mode,
                        "quality": job.quality,
                        "dispatch_preference": job.dispatch_preference,
                        "lyric_reasoning_mode": job.lyric_reasoning_mode,
                    },
                },
            )
        finally:
            db.close()

    @staticmethod
    def list_agents() -> list[AgentResponse]:
        db = SessionLocal()
        try:
            agents = db.query(AgentNode).order_by(AgentNode.created_at.desc()).all()
            return [
                AgentResponse(
                    id=a.id,
                    agent_name=a.agent_name,
                    status=a.status,
                    agent_mode=a.agent_mode,
                    hostname=a.hostname,
                    gpu_available=a.gpu_available,
                    gpu_name=a.gpu_name,
                    vram_gb=a.vram_gb,
                    cuda_available=a.cuda_available,
                    capabilities=a.capabilities_json,
                    model_packs=a.model_packs_json,
                    container_version=a.container_version,
                    last_heartbeat_at=a.last_heartbeat_at.isoformat() if a.last_heartbeat_at else None,
                    draining=a.draining,
                    created_at=a.created_at.isoformat() if a.created_at else None,
                )
                for a in agents
            ]
        finally:
            db.close()
