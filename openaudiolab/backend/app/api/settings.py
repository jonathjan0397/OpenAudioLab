from typing import Optional

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException

from app.auth.dependencies import require_admin
from app.db.models import User
from app.setup.service import SetupService

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    default_retention_days: Optional[int] = None
    storage_provider: Optional[str] = None
    enable_cpu_test_mode: Optional[bool] = None
    enable_cloud_workers: Optional[bool] = None
    default_lyric_reasoning_mode: Optional[str] = None
    max_lyric_revision_attempts: Optional[int] = None
    max_job_duration: Optional[int] = None


@router.get("")
async def get_settings(current_user: User = Depends(require_admin)):
    settings_map = {}
    for key in [
        "default_retention_days",
        "storage_provider",
        "enable_cpu_test_mode",
        "enable_cloud_workers",
        "default_lyric_reasoning_mode",
        "max_lyric_revision_attempts",
        "max_job_duration",
        "worker_registration_token",
    ]:
        value = SetupService.get_setting(key)
        settings_map[key] = value.get("value") if value else None

    settings_map["worker_registration_token"] = "[REDACTED]"

    return settings_map


@router.patch("")
async def update_settings(
    updates: SettingsUpdate,
    current_user: User = Depends(require_admin),
):
    results = {}
    if updates.default_retention_days is not None:
        SetupService.update_setting("default_retention_days", {"value": updates.default_retention_days})
        results["default_retention_days"] = updates.default_retention_days
    if updates.storage_provider is not None:
        SetupService.update_setting("storage_provider", {"value": updates.storage_provider})
        results["storage_provider"] = updates.storage_provider
    if updates.enable_cpu_test_mode is not None:
        SetupService.update_setting("enable_cpu_test_mode", {"value": updates.enable_cpu_test_mode})
        results["enable_cpu_test_mode"] = updates.enable_cpu_test_mode
    if updates.enable_cloud_workers is not None:
        SetupService.update_setting("enable_cloud_workers", {"value": updates.enable_cloud_workers})
        results["enable_cloud_workers"] = updates.enable_cloud_workers

    return {"updated": results}
