from datetime import datetime, timedelta, timezone
from typing import Optional

from app.core.enums import DEFAULT_PIPELINE, JobStatus, LyricsMode
from app.db.models import GenerationJob, JobStage
from app.db.session import SessionLocal
from app.jobs.schemas import JobCreateRequest, JobResponse, JobStageResponse
from app.jobs.state_machine import StateMachine


def _build_pipeline(request: JobCreateRequest) -> list[str]:
    pipeline = [s.value for s in DEFAULT_PIPELINE]

    if request.instrumental or request.lyrics_mode == LyricsMode.INSTRUMENTAL:
        skip_stages = {
            "lyrics_generation_or_ingestion",
            "lyric_brainstorm",
            "lyrics_structure_validation",
            "lyrics_reasoning",
            "lyrics_revision",
            "lyrics_humanization",
        }
        pipeline = [s for s in pipeline if s not in skip_stages]
    elif request.lyrics_mode == LyricsMode.PROVIDED:
        skip_stages = {
            "lyrics_generation_or_ingestion",
            "lyrics_reasoning",
            "lyrics_revision",
            "lyrics_humanization",
        }
        pipeline = [s for s in pipeline if s not in skip_stages]
    elif request.lyrics_mode == LyricsMode.HYBRID:
        skip_stages = {
            "lyrics_generation_or_ingestion",
        }
        pipeline = [s for s in pipeline if s not in skip_stages]
    elif request.lyrics_mode == LyricsMode.AI:
        pass

    return pipeline


class JobService:
    @staticmethod
    def create_job(request: JobCreateRequest, user_id: Optional[str] = None) -> JobResponse:
        db = SessionLocal()
        try:
            pipeline = _build_pipeline(request)
            retention_days = request.storage_retention_days
            expires_at = datetime.now(timezone.utc) + timedelta(days=retention_days)

            job = GenerationJob(
                user_id=user_id,
                status=JobStatus.CREATED.value,
                prompt=request.prompt,
                genre=request.genre,
                mood=request.mood,
                lyrics_mode=request.lyrics_mode.value,
                provided_lyrics=request.provided_lyrics,
                instrumental=request.instrumental,
                duration_seconds=request.duration_seconds,
                vocal_mode=request.vocal_mode,
                quality=request.quality.value,
                dispatch_preference=request.dispatch_preference.value,
                lyric_reasoning_mode=request.lyric_reasoning_mode.value,
                storage_retention_days=retention_days,
                expires_at=expires_at,
            )
            db.add(job)
            db.flush()

            for stage_name in pipeline:
                stage = JobStage(
                    job_id=job.id,
                    stage_name=stage_name,
                    status="pending",
                )
                db.add(stage)

            db.commit()
            db.refresh(job)

            StateMachine.transition_job(job.id, JobStatus.QUEUED)

            return JobService.get_job(job.id)
        finally:
            db.close()

    @staticmethod
    def get_job(job_id: str) -> Optional[JobResponse]:
        db = SessionLocal()
        try:
            job = db.query(GenerationJob).filter(GenerationJob.id == job_id).first()
            if not job:
                return None

            stages = db.query(JobStage).filter(JobStage.job_id == job_id).order_by(JobStage.created_at).all()

            return JobResponse(
                id=job.id,
                status=job.status,
                prompt=job.prompt,
                genre=job.genre,
                mood=job.mood,
                lyrics_mode=job.lyrics_mode,
                instrumental=job.instrumental,
                duration_seconds=job.duration_seconds,
                vocal_mode=job.vocal_mode,
                quality=job.quality,
                dispatch_preference=job.dispatch_preference,
                lyric_reasoning_mode=job.lyric_reasoning_mode,
                assigned_agent_id=job.assigned_agent_id,
                error_message=job.error_message,
                created_at=job.created_at.isoformat() if job.created_at else None,
                updated_at=job.updated_at.isoformat() if job.updated_at else None,
                expires_at=job.expires_at.isoformat() if job.expires_at else None,
                stages=[
                    JobStageResponse(
                        id=s.id,
                        stage_name=s.stage_name,
                        status=s.status,
                        started_at=s.started_at.isoformat() if s.started_at else None,
                        completed_at=s.completed_at.isoformat() if s.completed_at else None,
                        error_message=s.error_message,
                        metadata_json=s.metadata_json,
                    )
                    for s in stages
                ],
            )
        finally:
            db.close()

    @staticmethod
    def list_jobs(limit: int = 20, offset: int = 0) -> list[JobResponse]:
        db = SessionLocal()
        try:
            jobs = (
                db.query(GenerationJob)
                .order_by(GenerationJob.created_at.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            return [JobService.get_job(job.id) for job in jobs]
        finally:
            db.close()

    @staticmethod
    def cancel_job(job_id: str) -> bool:
        return StateMachine.transition_job(job_id, JobStatus.CANCELLED)

    @staticmethod
    def get_job_logs(job_id: str) -> list[dict]:
        db = SessionLocal()
        try:
            stages = db.query(JobStage).filter(JobStage.job_id == job_id).order_by(JobStage.created_at).all()
            logs = []
            for stage in stages:
                logs.append({
                    "timestamp": stage.started_at.isoformat() if stage.started_at else None,
                    "stage": stage.stage_name,
                    "status": stage.status,
                    "message": stage.error_message or f"Stage {stage.stage_name}: {stage.status}",
                    "metadata": stage.metadata_json,
                })
            return logs
        finally:
            db.close()
