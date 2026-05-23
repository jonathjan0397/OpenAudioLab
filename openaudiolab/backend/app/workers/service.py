from datetime import datetime, timezone
from typing import Optional

from app.core.config import settings
from app.core.security import generate_worker_api_token
from app.db.models import WorkerHeartbeat, WorkerNode
from app.db.session import SessionLocal
from app.workers.schemas import (
    HeartbeatRequest,
    HeartbeatResponse,
    JobRequestResponse,
    WorkerRegistrationRequest,
    WorkerRegistrationResponse,
    WorkerResponse,
)


class WorkerService:
    @staticmethod
    def register_worker(request: WorkerRegistrationRequest) -> WorkerRegistrationResponse:
        if request.registration_token != settings.WORKER_REGISTRATION_TOKEN:
            return WorkerRegistrationResponse(
                accepted=False,
                message="Invalid registration token",
            )

        db = SessionLocal()
        try:
            existing = db.query(WorkerNode).filter(WorkerNode.worker_name == request.worker_name).first()
            if existing:
                worker = existing
                worker.status = "registering"
                worker.gpu_available = request.gpu.get("available", False)
                worker.gpu_name = request.gpu.get("name")
                worker.vram_gb = request.gpu.get("vram_gb", 0)
                worker.cuda_available = request.gpu.get("cuda_available", False)
                worker.capabilities_json = request.capabilities
                worker.model_packs_json = request.model_packs
                worker.container_version = request.container_version
                worker.hostname = request.hostname
                worker.worker_mode = request.worker_mode
            else:
                worker_api_token = generate_worker_api_token()
                worker = WorkerNode(
                    worker_name=request.worker_name,
                    status="registering",
                    worker_mode=request.worker_mode,
                    hostname=request.hostname,
                    gpu_available=request.gpu.get("available", False),
                    gpu_name=request.gpu.get("name"),
                    vram_gb=request.gpu.get("vram_gb", 0),
                    cuda_available=request.gpu.get("cuda_available", False),
                    capabilities_json=request.capabilities,
                    model_packs_json=request.model_packs,
                    container_version=request.container_version,
                    worker_api_token=worker_api_token,
                )
                db.add(worker)

            db.commit()
            db.refresh(worker)

            worker.status = "idle"
            db.commit()

            return WorkerRegistrationResponse(
                accepted=True,
                worker_id=worker.id,
                worker_api_token=worker.worker_api_token,
                message="Worker registered successfully",
            )
        finally:
            db.close()

    @staticmethod
    def process_heartbeat(request: HeartbeatRequest, worker_api_token: str) -> HeartbeatResponse:
        db = SessionLocal()
        try:
            worker = db.query(WorkerNode).filter(
                WorkerNode.id == request.worker_id,
                WorkerNode.worker_api_token == worker_api_token,
            ).first()

            if not worker:
                return HeartbeatResponse(accepted=False)

            worker.status = request.status
            worker.last_heartbeat_at = datetime.now(timezone.utc)
            worker.draining = request.draining
            worker.container_version = request.container_version

            heartbeat = WorkerHeartbeat(
                worker_id=worker.id,
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

            update_required = request.container_version != settings.WORKER_VERSION
            drain_requested = worker.draining

            return HeartbeatResponse(
                accepted=True,
                update_required=update_required,
                drain_requested=drain_requested,
            )
        finally:
            db.close()

    @staticmethod
    def request_job(worker_id: str, worker_api_token: str) -> JobRequestResponse:
        db = SessionLocal()
        try:
            from app.db.models import GenerationJob
            from app.jobs.queue import JobQueue
            from app.core.enums import JobStatus

            worker = db.query(WorkerNode).filter(
                WorkerNode.id == worker_id,
                WorkerNode.worker_api_token == worker_api_token,
            ).first()

            if not worker or worker.status in ("offline", "draining"):
                return JobRequestResponse(job_available=False)

            job_id = JobQueue.dequeue_job()
            if not job_id:
                return JobRequestResponse(job_available=False)

            job = db.query(GenerationJob).filter(GenerationJob.id == job_id).first()
            if not job:
                return JobRequestResponse(job_available=False)

            job.status = JobStatus.ASSIGNED.value
            job.assigned_worker_id = worker_id
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
    def list_workers() -> list[WorkerResponse]:
        db = SessionLocal()
        try:
            workers = db.query(WorkerNode).order_by(WorkerNode.created_at.desc()).all()
            return [
                WorkerResponse(
                    id=w.id,
                    worker_name=w.worker_name,
                    status=w.status,
                    worker_mode=w.worker_mode,
                    hostname=w.hostname,
                    gpu_available=w.gpu_available,
                    gpu_name=w.gpu_name,
                    vram_gb=w.vram_gb,
                    cuda_available=w.cuda_available,
                    capabilities=w.capabilities_json,
                    model_packs=w.model_packs_json,
                    container_version=w.container_version,
                    last_heartbeat_at=w.last_heartbeat_at.isoformat() if w.last_heartbeat_at else None,
                    draining=w.draining,
                    created_at=w.created_at.isoformat() if w.created_at else None,
                )
                for w in workers
            ]
        finally:
            db.close()
