from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException

from app.setup.service import SetupService

router = APIRouter(prefix="/api/setup", tags=["setup"])


class SetupInitializeRequest(BaseModel):
    admin_email: str = Field(..., min_length=3, max_length=255)
    admin_password: str = Field(..., min_length=12)
    confirm_password: str = Field(...)
    site_name: str = Field(..., min_length=1, max_length=100)
    public_backend_url: str = Field(..., min_length=1)
    storage_provider: str = Field(default="local")
    default_retention_days: int = Field(default=7, ge=1, le=365)
    enable_cpu_test_mode: bool = Field(default=True)
    enable_cloud_workers: bool = Field(default=False)


@router.get("/status")
async def get_setup_status():
    return SetupService.get_setup_status()


@router.post("/initialize")
async def initialize_setup(request: SetupInitializeRequest):
    if request.admin_password != request.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")

    success, result = SetupService.initialize_setup(
        admin_email=request.admin_email,
        admin_password=request.admin_password,
        site_name=request.site_name,
        public_backend_url=request.public_backend_url,
        storage_provider=request.storage_provider,
        default_retention_days=request.default_retention_days,
        enable_cpu_test_mode=request.enable_cpu_test_mode,
        enable_cloud_workers=request.enable_cloud_workers,
    )

    if not success:
        if "errors" in result:
            raise HTTPException(status_code=400, detail=result["errors"])
        raise HTTPException(status_code=400, detail=result.get("error", "Setup failed"))

    return result
