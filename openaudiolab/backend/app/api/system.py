from fastapi import APIRouter

from app.core.config import settings
from app.setup.service import SetupService
from app.workers.service import WorkerService

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/status")
async def system_status():
    setup_status = SetupService.get_setup_status()
    workers = WorkerService.list_workers()

    gpu_available = any(w.gpu_available for w in workers)
    gpu_info = None
    for w in workers:
        if w.gpu_available:
            gpu_info = {"name": w.gpu_name, "vram_gb": w.vram_gb}
            break

    return {
        "backend_online": True,
        "database_online": True,
        "redis_online": True,
        "storage_online": True,
        "storage_provider": settings.STORAGE_PROVIDER,
        "local_gpu_status": "available" if gpu_available else "unavailable",
        "gpu_info": gpu_info,
        "configured_cloud_providers": ["vastai", "runpod"] if settings.ENABLE_CLOUD_WORKERS else [],
        "default_retention_days": settings.DEFAULT_RETENTION_DAYS,
        "setup_status": setup_status,
        "active_workers": len([w for w in workers if w.status == "idle"]),
        "total_workers": len(workers),
        "security_warnings": settings.validate_production_secrets(),
    }
