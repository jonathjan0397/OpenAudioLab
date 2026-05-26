from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.core.enums import DispatchPreference, LyricsMode, LyricReasoningMode, Quality


class JobCreateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)
    genre: Optional[str] = Field(None, max_length=100)
    mood: Optional[str] = Field(None, max_length=255)
    lyrics_mode: LyricsMode = LyricsMode.AI
    provided_lyrics: Optional[str] = Field(None, max_length=10000)
    instrumental: bool = False
    duration_seconds: int = Field(default=90, ge=5, le=600)
    vocal_mode: str = Field(default="male", max_length=20)
    quality: Quality = Quality.DRAFT
    dispatch_preference: DispatchPreference = DispatchPreference.AUTO
    lyric_reasoning_mode: LyricReasoningMode = LyricReasoningMode.BALANCED
    storage_retention_days: int = Field(default=7, ge=1, le=365)


class JobStageResponse(BaseModel):
    id: str
    stage_name: str
    status: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None
    metadata_json: Optional[dict] = None


class JobResponse(BaseModel):
    id: str
    status: str
    prompt: str
    genre: Optional[str] = None
    mood: Optional[str] = None
    lyrics_mode: str
    instrumental: bool
    duration_seconds: int
    vocal_mode: Optional[str] = None
    quality: str
    dispatch_preference: str
    lyric_reasoning_mode: Optional[str] = None
    assigned_agent_id: Optional[str] = None
    error_message: Optional[str] = None
    created_at: str
    updated_at: Optional[str] = None
    expires_at: Optional[str] = None
    stages: list[JobStageResponse] = []


class JobLogEntry(BaseModel):
    timestamp: str
    stage: str
    level: str
    message: str
    metadata: Optional[dict] = None


class StageUpdateRequest(BaseModel):
    stage_name: str
    status: str
    metadata: Optional[dict] = None
    error_message: Optional[str] = None
