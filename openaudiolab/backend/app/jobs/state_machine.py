from datetime import datetime, timezone

from app.core.enums import JobStatus, StageStatus
from app.db.models import GenerationJob, JobStage
from app.db.session import SessionLocal

VALID_TRANSITIONS = {
    JobStatus.CREATED: [JobStatus.QUEUED, JobStatus.CANCELLED, JobStatus.FAILED],
    JobStatus.QUEUED: [JobStatus.WAITING_FOR_WORKER, JobStatus.ASSIGNED, JobStatus.CANCELLED, JobStatus.FAILED],
    JobStatus.WAITING_FOR_WORKER: [JobStatus.PROVISIONING_WORKER, JobStatus.ASSIGNED, JobStatus.CANCELLED, JobStatus.FAILED],
    JobStatus.PROVISIONING_WORKER: [JobStatus.ASSIGNED, JobStatus.FAILED, JobStatus.CANCELLED],
    JobStatus.ASSIGNED: [JobStatus.RUNNING, JobStatus.FAILED, JobStatus.CANCELLED],
    JobStatus.RUNNING: [JobStatus.STAGE_COMPLETED, JobStatus.UPLOADING_RESULTS, JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED],
    JobStatus.STAGE_COMPLETED: [JobStatus.RUNNING, JobStatus.UPLOADING_RESULTS, JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED],
    JobStatus.UPLOADING_RESULTS: [JobStatus.COMPLETED, JobStatus.FAILED],
    JobStatus.COMPLETED: [],
    JobStatus.FAILED: [],
    JobStatus.CANCELLED: [],
    JobStatus.EXPIRED: [],
}

VALID_STAGE_TRANSITIONS = {
    StageStatus.PENDING: [StageStatus.RUNNING, StageStatus.SKIPPED],
    StageStatus.RUNNING: [StageStatus.COMPLETED, StageStatus.FAILED, StageStatus.SKIPPED],
    StageStatus.COMPLETED: [],
    StageStatus.FAILED: [],
    StageStatus.SKIPPED: [],
}


class StateMachine:
    @staticmethod
    def can_transition(current: JobStatus, target: JobStatus) -> bool:
        allowed = VALID_TRANSITIONS.get(current, [])
        return target in allowed

    @staticmethod
    def transition_job(job_id: str, new_status: JobStatus, error_message: str = None) -> bool:
        db = SessionLocal()
        try:
            job = db.query(GenerationJob).filter(GenerationJob.id == job_id).first()
            if not job:
                return False

            current_status = JobStatus(job.status)
            if not StateMachine.can_transition(current_status, new_status):
                return False

            job.status = new_status.value
            job.updated_at = datetime.now(timezone.utc)
            if error_message:
                job.error_message = error_message
            db.commit()
            return True
        finally:
            db.close()

    @staticmethod
    def can_stage_transition(current: StageStatus, target: StageStatus) -> bool:
        allowed = VALID_STAGE_TRANSITIONS.get(current, [])
        return target in allowed

    @staticmethod
    def transition_stage(stage_id: str, new_status: StageStatus, metadata: dict = None, error_message: str = None) -> bool:
        db = SessionLocal()
        try:
            stage = db.query(JobStage).filter(JobStage.id == stage_id).first()
            if not stage:
                return False

            current_status = StageStatus(stage.status)
            if not StateMachine.can_stage_transition(current_status, new_status):
                return False

            stage.status = new_status.value
            if new_status == StageStatus.RUNNING and not stage.started_at:
                stage.started_at = datetime.now(timezone.utc)
            elif new_status in (StageStatus.COMPLETED, StageStatus.FAILED, StageStatus.SKIPPED):
                stage.completed_at = datetime.now(timezone.utc)
            if metadata:
                stage.metadata_json = metadata
            if error_message:
                stage.error_message = error_message
            db.commit()
            return True
        finally:
            db.close()

    @staticmethod
    def initialize_job_stages(job_id: str, pipeline: list[str]) -> list[str]:
        db = SessionLocal()
        try:
            stage_ids = []
            for stage_name in pipeline:
                stage = JobStage(
                    job_id=job_id,
                    stage_name=stage_name,
                    status=StageStatus.PENDING.value,
                )
                db.add(stage)
                db.flush()
                stage_ids.append(stage.id)
            db.commit()
            return stage_ids
        finally:
            db.close()
