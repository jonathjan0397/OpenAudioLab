"""Strict request/response schemas. Unknown fields fail validation."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

LyricsOrigin = Literal["human", "frontend_llm", "mixed"]
OutputOption = Literal["mix_wav", "mix_mp3", "stems_wav", "stems_zip"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GenerateJobRequest(StrictModel):
    operation: str
    model_id: str
    music_description: str = Field(min_length=1, max_length=2000)
    lyrics: str | None = None
    lyrics_origin: LyricsOrigin | None = None
    instrumental: bool = False
    duration_seconds: int | None = Field(default=None, ge=1, le=600)
    seed: int | None = Field(default=None, ge=0, le=2**63 - 1)
    controls: dict[str, Any] = Field(default_factory=dict)
    outputs: list[OutputOption] = Field(default_factory=lambda: ["mix_wav", "mix_mp3"])
    artist_profile_version_id: str | None = None
    client_reference: str | None = Field(default=None, max_length=200)

    @field_validator("outputs")
    @classmethod
    def _dedupe_outputs(cls, value: list[str]) -> list[str]:
        return sorted(set(value))

    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def request_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


class JobAcceptedResponse(BaseModel):
    job_id: str
    status: str
    model_id: str
    model_revision: str
    status_url: str
    events_url: str
    poll_after_seconds: int
    required_notices: list[str]


class JobDetailResponse(BaseModel):
    job_id: str
    status: str
    operation: str
    model_id: str
    model_revision: str
    attempt_number: int
    stage: str | None
    progress: float | None
    progress_source: str | None
    lyrics_sha256: str | None
    lyrics_origin: str | None
    client_reference: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    assets_expired_at: datetime | None
    status_url: str
    events_url: str
    poll_after_seconds: int
    required_notices: list[str]


class JobPage(BaseModel):
    jobs: list[JobDetailResponse]
    next_cursor: str | None


class CancelResponse(BaseModel):
    job_id: str
    status: str
    upstream_termination_supported: bool


class ArtifactsResponse(BaseModel):
    job_id: str
    artifacts: list[dict[str, Any]]


class ModelSummary(BaseModel):
    model_id: str
    display_name: str
    enabled: bool
    availability: str
    commercial_policy: str
    required_notices: list[str]
    capabilities: dict[str, bool]


class ModelDetail(ModelSummary):
    revision: str
    license_status: str
    supported_controls: list[str]
    supports_seed: bool
    supports_duration: bool
    min_duration_seconds: int
    max_duration_seconds: int
    output_options: list[str]
