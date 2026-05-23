from typing import Optional

from pydantic import BaseModel, Field


class WorkerRegistrationRequest(BaseModel):
    worker_id: Optional[str] = None
    worker_name: str = Field(..., min_length=1, max_length=255)
    worker_mode: str = Field(default="lite", max_length=30)
    hostname: Optional[str] = None
    registration_token: str = Field(..., min_length=1)
    gpu: dict = Field(default_factory=lambda: {
        "available": False,
        "name": None,
        "vram_gb": 0,
        "cuda_available": False,
    })
    capabilities: dict = Field(default_factory=lambda: {
        "lyrics": True,
        "lyrics_reasoning": True,
        "music_generation": False,
        "cpu_test_generation": True,
        "daw_processing": True,
        "effects": True,
        "mastering": True,
        "zip_export": True,
    })
    model_packs: list[str] = Field(default_factory=list)
    container_version: str = Field(default="0.1.0")


class WorkerRegistrationResponse(BaseModel):
    accepted: bool
    worker_id: Optional[str] = None
    worker_api_token: Optional[str] = None
    message: Optional[str] = None


class HeartbeatRequest(BaseModel):
    worker_id: str
    status: str = "idle"
    active_job_id: Optional[str] = None
    gpu_utilization: Optional[float] = None
    vram_used_gb: Optional[float] = None
    disk_free_gb: Optional[float] = None
    container_version: str = "0.1.0"
    draining: bool = False


class HeartbeatResponse(BaseModel):
    accepted: bool
    update_required: bool = False
    drain_requested: bool = False


class WorkerResponse(BaseModel):
    id: str
    worker_name: str
    status: str
    worker_mode: str
    hostname: Optional[str] = None
    gpu_available: bool
    gpu_name: Optional[str] = None
    vram_gb: float
    cuda_available: bool
    capabilities: Optional[dict] = None
    model_packs: Optional[list[str]] = None
    container_version: Optional[str] = None
    last_heartbeat_at: Optional[str] = None
    draining: bool
    created_at: Optional[str] = None


class JobRequestResponse(BaseModel):
    job_available: bool
    job: Optional[dict] = None


class StageUpdateRequest(BaseModel):
    stage_name: str
    status: str
    metadata: Optional[dict] = None
    error_message: Optional[str] = None
