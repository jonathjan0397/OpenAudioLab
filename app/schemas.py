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
    title: str | None = Field(default=None, max_length=200)
    lyrics: str | None = None
    lyrics_origin: LyricsOrigin | None = None
    instrumental: bool = False
    duration_seconds: int | None = Field(default=None, ge=1, le=600)
    seed: int | None = Field(default=None, ge=0, le=2**63 - 1)
    controls: dict[str, Any] = Field(default_factory=dict)
    outputs: list[OutputOption] = Field(default_factory=lambda: ["mix_wav", "mix_mp3"])
    artist_profile_version_id: str | None = None
    lora_id: str | None = None
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
    seed: int | None = None
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


class ProjectCreate(StrictModel):
    name: str = Field(min_length=1, max_length=200)


class ProjectPatch(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    active_version_id: str | None = None


class ProjectResponse(BaseModel):
    project_id: str
    name: str
    active_version_id: str | None
    etag: str
    created_at: datetime
    updated_at: datetime


class ProjectPage(BaseModel):
    projects: list[ProjectResponse]


class VersionCreate(StrictModel):
    source_job_id: str | None = None
    source_asset_id: str | None = None
    label: str | None = Field(default=None, max_length=200)


class VersionResponse(BaseModel):
    version_id: str
    project_id: str
    kind: str
    label: str | None
    source_job_id: str | None
    source_asset_id: str | None
    parent_version_id: str | None
    manifest: dict[str, Any]
    created_at: datetime


class VersionPage(BaseModel):
    versions: list[VersionResponse]


class RestoreRequest(StrictModel):
    version_id: str


class UploadCreate(StrictModel):
    filename: str = Field(min_length=1, max_length=300)
    content_type: str | None = Field(default=None, max_length=120)


class UploadResponse(BaseModel):
    upload_id: str
    status: str
    data_url: str
    expires_at: datetime
    bytes: int | None
    sha256: str | None
    asset_id: str | None
    error: str | None


class AssetResponse(BaseModel):
    asset_id: str
    job_id: str | None
    role: str
    kind: str
    source_asset_id: str | None
    stem_source: str | None
    stem_category: str | None
    processing: str | None
    mime: str
    bytes: int
    sha256: str
    sample_rate: int | None
    channels: int | None
    duration_seconds: float | None
    synthetic: bool
    created_at: datetime
    expires_at: datetime | None
    deleted: bool


class WavSettings(StrictModel):
    sample_rate: Literal["native", 44100, 48000] = "native"
    encoding: Literal["pcm16", "pcm24"] = "pcm16"


class Mp3Settings(StrictModel):
    bitrate_kbps: Literal[128, 192, 256, 320] = 320


class ExportRequest(StrictModel):
    source_version_id: str
    outputs: list[OutputOption] = Field(min_length=1)
    wav: WavSettings | None = None
    mp3: Mp3Settings | None = None
    stem_set: Literal["available"] = "available"

    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def request_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


class ArtistProfileCreate(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    style: dict[str, Any] = Field(default_factory=dict)
    singer: dict[str, Any] = Field(default_factory=dict)
    bio: str | None = Field(default=None, max_length=1000)


class ArtistProfilePatch(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    style: dict[str, Any] | None = None
    singer: dict[str, Any] | None = None
    sharing: str | None = Field(default=None, pattern=r"^(private|public)$")
    bio: str | None = Field(default=None, max_length=1000)


class ArtistProfileResponse(BaseModel):
    profile_id: str
    name: str
    slug: str | None = None
    bio: str | None = None
    avatar_key: str | None = None
    style: dict[str, Any]
    singer: dict[str, Any]
    sharing_policy: str
    active_version_id: str | None
    etag: str
    created_at: datetime
    updated_at: datetime


class RightsCreate(StrictModel):
    purpose: str
    declaration: str = Field(min_length=1, max_length=500)
    asset_id: str | None = None


class RightsResponse(BaseModel):
    record_id: str
    profile_id: str
    asset_id: str | None
    purpose: str
    declaration: str
    declared_at: datetime


class DatasetCreate(StrictModel):
    name: str = Field(min_length=1, max_length=200)


class DatasetResponse(BaseModel):
    dataset_id: str
    profile_id: str
    name: str
    status: str
    created_at: datetime


class TrackCreate(StrictModel):
    asset_id: str
    lyrics: str | None = Field(default=None, max_length=20000)
    language: str | None = Field(default=None, max_length=20)
    labels: dict[str, Any] = Field(default_factory=dict)


class TrackResponse(BaseModel):
    track_id: str
    dataset_id: str
    asset_id: str
    lyrics: str | None
    language: str | None
    labels: dict[str, Any]
    split: str | None


class DatasetVersionResponse(BaseModel):
    dataset_version_id: str
    dataset_id: str
    version_number: int
    frozen_sha256: str
    split: dict[str, Any]
    report: dict[str, Any]
    created_at: datetime


class TrainingCreate(StrictModel):
    profile_id: str
    dataset_version_id: str
    base_model_id: str | None = None
    recipe_revision: str | None = None
    budget: dict[str, Any] | None = None
    hyperparams: dict[str, Any] = Field(default_factory=dict)
    seed: int | None = Field(default=None, ge=0, le=2**31 - 1)

    def canonical_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    def request_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


class EvaluationCreate(StrictModel):
    profile_version_id: str
    prompts: list[str] = Field(min_length=1, max_length=3)

    @field_validator("prompts")
    @classmethod
    def _prompt_lengths(cls, value: list[str]) -> list[str]:
        if any(not p.strip() or len(p) > 500 for p in value):
            raise ValueError("Each evaluation prompt must be 1-500 characters.")
        return value

    def canonical_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    def request_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


class ProfileVersionResponse(BaseModel):
    version_id: str
    profile_id: str
    mechanism: str
    base_model_id: str
    base_revision: str
    recipe_revision: str
    dataset_version_id: str | None
    artifacts: dict[str, Any]
    evaluation_status: str
    state: str
    created_at: datetime


class ActivateRequest(StrictModel):
    version_id: str


class ReviewRequest(StrictModel):
    review: Literal["accept", "reject"]
