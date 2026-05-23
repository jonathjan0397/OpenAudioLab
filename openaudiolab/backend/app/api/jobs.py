from fastapi import APIRouter, Depends, HTTPException

from app.auth.dependencies import require_auth
from app.db.models import User
from app.jobs.schemas import JobCreateRequest
from app.jobs.service import JobService

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("")
async def create_job(request: JobCreateRequest, current_user: User = Depends(require_auth)):
    job = JobService.create_job(request, user_id=current_user.id)
    return job


@router.get("")
async def list_jobs(limit: int = 20, offset: int = 0, current_user: User = Depends(require_auth)):
    return JobService.list_jobs(limit=limit, offset=offset)


@router.get("/{job_id}")
async def get_job(job_id: str, current_user: User = Depends(require_auth)):
    job = JobService.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: str, current_user: User = Depends(require_auth)):
    job = JobService.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    success = JobService.cancel_job(job_id)
    if not success:
        raise HTTPException(status_code=400, detail="Cannot cancel job in current state")
    return {"message": "Job cancelled"}


@router.post("/{job_id}/retry")
async def retry_job(job_id: str, current_user: User = Depends(require_auth)):
    return {"message": "Retry is a placeholder in this version"}


@router.get("/{job_id}/logs")
async def get_job_logs(job_id: str, current_user: User = Depends(require_auth)):
    job = JobService.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobService.get_job_logs(job_id)


@router.get("/{job_id}/download")
async def download_job(job_id: str, current_user: User = Depends(require_auth)):
    from app.storage.service import StorageService

    job = JobService.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "completed":
        raise HTTPException(status_code=400, detail="Job is not complete")

    zip_key = StorageService.get_job_storage_key(job_id, "exports/final.zip")
    url = StorageService.generate_signed_url(zip_key, expires_in=3600)
    if url is None:
        raise HTTPException(status_code=404, detail="Download not available")
    return {"download_url": url, "expires_in": 3600}
