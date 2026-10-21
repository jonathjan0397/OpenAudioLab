"""Authoritative durable records. Queue messages are delivery hints only."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import Boolean, Date, DateTime, Float, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

JOB_STATUSES = (
    "queued",
    "waiting_for_worker",
    "running",
    "cancelling",
    "succeeded",
    "failed",
    "cancelled",
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_uuid() -> str:
    return str(uuid4())


class Job(Base):
    __tablename__ = "jobs"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String(36), unique=True, default=new_uuid)
    owner_id: Mapped[str] = mapped_column(String(80), index=True)
    operation: Mapped[str] = mapped_column(String(40))
    model_id: Mapped[str] = mapped_column(String(80))
    model_revision: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(30), default="queued")
    stage: Mapped[str | None] = mapped_column(String(40), nullable=True)
    progress: Mapped[float | None] = mapped_column(nullable=True)
    progress_source: Mapped[str | None] = mapped_column(String(30), nullable=True)
    request_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    request_hash: Mapped[str] = mapped_column(String(64))
    lyrics: Mapped[str | None] = mapped_column(Text, nullable=True)
    lyrics_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lyrics_origin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    client_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(255))
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assets_expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_jobs_owner_seq", "owner_id", "seq"),)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[str] = mapped_column(String(80))
    route: Mapped[str] = mapped_column(String(120))
    key: Mapped[str] = mapped_column(String(255))
    request_hash: Mapped[str] = mapped_column(String(64))
    job_id: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("owner_id", "route", "key", name="uq_idempotency_owner_route_key"),)


class JobAttempt(Base):
    __tablename__ = "job_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    job_id: Mapped[str] = mapped_column(String(36), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    worker_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="running")
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    upstream_task_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    engine_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("job_id", "attempt_number", name="uq_attempt_job_number"),)


class JobEvent(Base):
    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(36), index=True)
    attempt_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    event: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30))
    stage: Mapped[str | None] = mapped_column(String(40), nullable=True)
    progress: Mapped[float | None] = mapped_column(nullable=True)
    message: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OutboxRecord(Base):
    __tablename__ = "outbox_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(36), index=True)
    queue: Mapped[str] = mapped_column(String(160))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    job_id: Mapped[str] = mapped_column(String(36), index=True)
    owner_id: Mapped[str] = mapped_column(String(80), index=True)
    attempt_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    storage_key: Mapped[str] = mapped_column(String(500), unique=True)
    role: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(20), default="generated")
    source_asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    stem_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    stem_category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    processing: Mapped[str | None] = mapped_column(String(120), nullable=True)
    mime: Mapped[str] = mapped_column(String(80))
    bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    sample_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    channels: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(nullable=True)
    synthetic: Mapped[bool] = mapped_column(default=False)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    slug: Mapped[str | None] = mapped_column(String(80), nullable=True)
    shared: Mapped[bool] = mapped_column(default=False)
    tags_json: Mapped[list] = mapped_column(JSON, default=list)
    manifest_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    purge_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Worker(Base):
    __tablename__ = "workers"

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    drain: Mapped[bool] = mapped_column(default=False)
    gpu_util: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vram_used_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vram_total_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    unhealthy_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_heartbeat: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    owner_id: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(200))
    active_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    etag_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProjectVersion(Base):
    __tablename__ = "project_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    owner_id: Mapped[str] = mapped_column(String(80), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    parent_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    manifest: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UploadSession(Base):
    __tablename__ = "upload_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    owner_id: Mapped[str] = mapped_column(String(80), index=True)
    filename: Mapped[str] = mapped_column(String(300))
    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ArtistProfile(Base):
    __tablename__ = "artist_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    owner_id: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str | None] = mapped_column(String(220), nullable=True, unique=True)
    bio: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    avatar_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    style_json: Mapped[dict] = mapped_column(JSON, default=dict)
    singer_json: Mapped[dict] = mapped_column(JSON, default=dict)
    sharing_policy: Mapped[str] = mapped_column(String(20), default="private")
    is_main: Mapped[bool] = mapped_column(Boolean, default=False)
    default_voice_profile_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    etag_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# --- Universal Artist Identity System (UAIS) --------------------------------
#
# An Artist's voice is a persistent, portable identity asset: one canonical
# versioned voice profile per artist, one training library with immutable
# frozen versions, and a registry of model-specific adapters. Durable records
# are authoritative; queue messages are delivery hints only.


class VoiceProfile(Base):
    """Versioned canonical voice identity, independent of any generation model."""

    __tablename__ = "voice_profiles"
    __table_args__ = (UniqueConstraint("artist_profile_id", "version_number", name="uq_voiceprofile_artist_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    artist_profile_id: Mapped[str] = mapped_column(String(36), index=True)
    owner_id: Mapped[str] = mapped_column(String(80), index=True)
    version_number: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|analyzed|training|ready|archived
    dataset_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    identity_json: Mapped[dict] = mapped_column(JSON, default=dict)      # acoustically measured attributes
    description_json: Mapped[dict] = mapped_column(JSON, default=dict)   # user-selected descriptive attributes
    performance_json: Mapped[dict] = mapped_column(JSON, default=dict)   # performance profile settings
    embeddings_json: Mapped[dict] = mapped_column(JSON, default=dict)    # {model, input_type, recordings, centroid}
    analysis_model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class VoiceDataset(Base):
    """One training library per artist; recordings are immutable once frozen."""

    __tablename__ = "voice_datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    artist_profile_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    owner_id: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(200), default="Training library")
    latest_version_number: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class VoiceRecording(Base):
    """An uploaded training recording with QC evidence and consent record."""

    __tablename__ = "voice_recordings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    dataset_id: Mapped[str] = mapped_column(String(36), index=True)
    artist_profile_id: Mapped[str] = mapped_column(String(36), index=True)
    owner_id: Mapped[str] = mapped_column(String(80), index=True)
    asset_id: Mapped[str] = mapped_column(String(36))
    filename: Mapped[str] = mapped_column(String(300), default="")
    sha256: Mapped[str] = mapped_column(String(64), default="")
    bytes: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[float | None] = mapped_column(nullable=True)
    sample_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    channels: Mapped[int | None] = mapped_column(Integer, nullable=True)
    qc_json: Mapped[dict] = mapped_column(JSON, default=dict)
    consent_json: Mapped[dict] = mapped_column(JSON, default=dict)
    vocal_asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    separation_json: Mapped[dict] = mapped_column(JSON, default=dict)
    state: Mapped[str] = mapped_column(String(20), default="active")  # active|removed
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class VoiceDatasetVersion(Base):
    """Immutable frozen snapshot of the library at finalize time."""

    __tablename__ = "voice_dataset_versions"
    __table_args__ = (UniqueConstraint("dataset_id", "version_number", name="uq_voicedsv_dataset_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    dataset_id: Mapped[str] = mapped_column(String(36), index=True)
    owner_id: Mapped[str] = mapped_column(String(80), index=True)
    version_number: Mapped[int] = mapped_column(Integer, default=1)
    frozen_sha256: Mapped[str] = mapped_column(String(64))
    manifest_json: Mapped[dict] = mapped_column(JSON, default=dict)
    report_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VoiceAdapter(Base):
    """Model-specific voice representation bound to one exact checkpoint."""

    __tablename__ = "voice_adapters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    artist_profile_id: Mapped[str] = mapped_column(String(36), index=True)
    owner_id: Mapped[str] = mapped_column(String(80), index=True)
    voice_profile_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    dataset_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    model_selection: Mapped[str] = mapped_column(String(80))
    engine_model: Mapped[str] = mapped_column(String(120), default="")
    base_revision: Mapped[str] = mapped_column(String(120), default="")
    adapter_format: Mapped[str] = mapped_column(String(30), default="peft_lora")
    architecture_json: Mapped[dict] = mapped_column(JSON, default=dict)
    training_config_json: Mapped[dict] = mapped_column(JSON, default=dict)
    training_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    storage_prefix: Mapped[str] = mapped_column(String(500), default="")
    files_json: Mapped[list] = mapped_column(JSON, default=list)
    adapter_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    state: Mapped[str] = mapped_column(String(20), default="training")
    # training|ready|validated|stale|failed|retired
    metrics_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    validation_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    limitations_json: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class VoiceAnalysis(Base):
    """One Voice Identity Analysis run over a frozen dataset version."""

    __tablename__ = "voice_analyses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    artist_profile_id: Mapped[str] = mapped_column(String(36), index=True)
    owner_id: Mapped[str] = mapped_column(String(80), index=True)
    dataset_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    job_id: Mapped[str] = mapped_column(String(36), index=True)
    embedding_model: Mapped[str] = mapped_column(String(80))
    input_type: Mapped[str] = mapped_column(String(20), default="full_mix")
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Lora(Base):
    """Registry of reusable adapters (style/genre/voice) selectable by tag or id."""

    __tablename__ = "loras"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    kind: Mapped[str] = mapped_column(String(20), default="style")
    tags_json: Mapped[list] = mapped_column(JSON, default=list)
    storage_prefix: Mapped[str] = mapped_column(String(500), default="")
    files_json: Mapped[list] = mapped_column(JSON, default=list)
    base_model_id: Mapped[str] = mapped_column(String(80), default="ace-step-1.5")
    base_revision: Mapped[str] = mapped_column(String(120), default="")
    default_scale: Mapped[float] = mapped_column(Float, default=1.0)
    auto_apply: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str] = mapped_column(String(20), default="active")
    provenance: Mapped[str] = mapped_column(String(20), default="external")
    adapter_id: Mapped[str | None] = mapped_column(String(36), nullable=True)  # UAIS VoiceAdapter provenance
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    """Site account (cookie-session auth). Separate from bearer-token owners."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(20), default="user")
    state: Mapped[str] = mapped_column(String(20), default="active")
    plan: Mapped[str] = mapped_column(String(20), default="free")
    stripe_customer_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    subscription_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    credits_balance: Mapped[int] = mapped_column(Integer, default=0)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    avatar_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    bio: Mapped[str | None] = mapped_column(String(500), nullable=True)
    active_workspace_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    token_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SiteSetting(Base):
    __tablename__ = "site_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(String(500), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class VastInstance(Base):
    """Recently used Vast.ai nodes kept for fast restart instead of fresh create."""

    __tablename__ = "vast_instances"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    vast_instance_id: Mapped[str] = mapped_column(String(60), unique=True)
    hostname: Mapped[str | None] = mapped_column(String(120), nullable=True)
    role: Mapped[str] = mapped_column(String(40), default="engine")
    gpu_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    dph: Mapped[float | None] = mapped_column(nullable=True)  # offer $/hr at creation, for cost accounting
    state: Mapped[str] = mapped_column(String(20), default="running")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Favorite(Base):
    __tablename__ = "favorites"
    __table_args__ = (UniqueConstraint("owner_id", "asset_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    owner_id: Mapped[str] = mapped_column(String(80), index=True)
    asset_id: Mapped[str] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ArtistFollow(Base):
    __tablename__ = "artist_follows"
    __table_args__ = (UniqueConstraint("owner_id", "profile_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    owner_id: Mapped[str] = mapped_column(String(80), index=True)
    profile_id: Mapped[str] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    owner_id: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(120))
    key_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    key_prefix: Mapped[str] = mapped_column(String(16), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PlayEvent(Base):
    __tablename__ = "play_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    asset_id: Mapped[str] = mapped_column(String(36), index=True)
    viewer_id: Mapped[str] = mapped_column(String(80), default="anon")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CreditEntry(Base):
    __tablename__ = "credit_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    owner_id: Mapped[str] = mapped_column(String(80), index=True)
    delta: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(60))
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(160), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BillingEvent(Base):
    """Payment/invoice/refund audit trail for Stripe-backed billing (Milestone 2)."""

    __tablename__ = "billing_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    owner_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    stripe_event_id: Mapped[str | None] = mapped_column(String(120), nullable=True, unique=True)
    checkout_session_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    payment_intent_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    invoice_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    subscription_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    item_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    amount_usd: Mapped[int] = mapped_column(Integer, default=0)
    credits: Mapped[int] = mapped_column(Integer, default=0)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="recorded")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Workspace(Base):
    """Customer-facing song collection for organising tracks (M17)."""

    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    owner_id: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(200))
    artist_profile_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    is_default: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkspaceSong(Base):
    """A saved song recipe (name, lyrics, tags, seed) so it can be reproduced."""

    __tablename__ = "workspace_songs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    owner_id: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(200), default="Untitled")
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    lyrics: Mapped[str | None] = mapped_column(Text, nullable=True)
    style_tags: Mapped[list] = mapped_column(JSON, default=list)
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    instrumental: Mapped[bool] = mapped_column(default=False)
    asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ErrorLog(Base):
    """Advanced structured error log for agent triage (M17)."""

    __tablename__ = "error_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    component: Mapped[str] = mapped_column(String(40), index=True)
    route: Mapped[str | None] = mapped_column(String(120), nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str] = mapped_column(String(60), index=True)
    message: Mapped[str] = mapped_column(Text)
    traceback: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_json: Mapped[dict] = mapped_column(JSON, default=dict)
    job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    fingerprint: Mapped[str | None] = mapped_column(String(160), nullable=True)
    resolved: Mapped[bool] = mapped_column(default=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class ArtistSong(Base):
    """Curated song on a public artist profile (M17)."""

    __tablename__ = "artist_songs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    profile_id: Mapped[str] = mapped_column(String(36), index=True)
    owner_id: Mapped[str] = mapped_column(String(80), index=True)
    asset_id: Mapped[str] = mapped_column(String(36), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Pricing(Base):
    """DB-backed plan/pack pricing so admins can edit it (M17)."""

    __tablename__ = "pricing"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), index=True)
    name: Mapped[str] = mapped_column(String(120))
    price_usd: Mapped[int] = mapped_column(Integer, default=0)
    credits: Mapped[int] = mapped_column(Integer, default=0)
    position: Mapped[int] = mapped_column(Integer, default=0)
    visible: Mapped[bool] = mapped_column(Boolean, default=True)


class GuestSession(Base):
    __tablename__ = "guest_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    token_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    policy_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    policy_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    marketing_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    claimed_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)


class GuestQuotaCounter(Base):
    __tablename__ = "guest_quota_counters"
    __table_args__ = (UniqueConstraint("guest_id", "day"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    guest_id: Mapped[str] = mapped_column(String(36), index=True)
    day: Mapped[object] = mapped_column(Date)
    used: Mapped[int] = mapped_column(Integer, default=0)
    limit: Mapped[int] = mapped_column(Integer, default=4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class GuestQuotaReservation(Base):
    __tablename__ = "guest_quota_reservations"
    __table_args__ = (UniqueConstraint("guest_id", "job_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    guest_id: Mapped[str] = mapped_column(String(36), index=True)
    job_id: Mapped[str] = mapped_column(String(36), index=True)
    day: Mapped[object] = mapped_column(Date)
    takes: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="reserved", index=True)
    reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PolicyDocument(Base):
    __tablename__ = "policy_documents"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    version: Mapped[str] = mapped_column(String(80))
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class PolicyAcceptance(Base):
    __tablename__ = "policy_acceptances"
    __table_args__ = (UniqueConstraint("subject_type", "subject_id", "policy_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    subject_type: Mapped[str] = mapped_column(String(20), index=True)
    subject_id: Mapped[str] = mapped_column(String(80), index=True)
    policy_version: Mapped[str] = mapped_column(String(80), index=True)
    documents_json: Mapped[dict] = mapped_column(JSON, default=dict)
    marketing_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)


class AuthToken(Base):
    __tablename__ = "auth_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    purpose: Mapped[str] = mapped_column(String(40), index=True)
    token_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SubscriptionPeriod(Base):
    __tablename__ = "subscription_periods"
    __table_args__ = (UniqueConstraint("stripe_subscription_id", "period_start"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    plan: Mapped[str] = mapped_column(String(40))
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    stripe_invoice_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="recorded", index=True)
    credits: Mapped[int] = mapped_column(Integer, default=0)
    amount_usd: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AbuseReport(Base):
    __tablename__ = "abuse_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    reporter_owner_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    subject_type: Mapped[str] = mapped_column(String(40), default="asset")
    subject_id: Mapped[str] = mapped_column(String(80), index=True)
    reason: Mapped[str] = mapped_column(String(120))
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="open", index=True)
    decision: Mapped[str | None] = mapped_column(String(200), nullable=True)
    appeal_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AdminAudit(Base):
    __tablename__ = "admin_audits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    admin_id: Mapped[str] = mapped_column(String(80), index=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    target_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    context_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Quote(Base):
    """Server-issued, owner-bound credit quote that binds a model/profile/controls
    snapshot to an exact charge until it is consumed by a job or expires."""

    __tablename__ = "quotes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    owner_id: Mapped[str] = mapped_column(String(80), index=True)
    request_hash: Mapped[str] = mapped_column(String(64), index=True)
    model_selection: Mapped[str] = mapped_column(String(80))
    engine_model: Mapped[str] = mapped_column(String(120))
    execution_profile_id: Mapped[str] = mapped_column(String(80))
    controls_json: Mapped[dict] = mapped_column(JSON, default=dict)
    context_json: Mapped[dict] = mapped_column(JSON, default=dict)  # src/reference/lyric hashes, duration, outputs, task
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    takes: Mapped[int] = mapped_column(Integer, default=1)
    reserved_credits: Mapped[int] = mapped_column(Integer, default=0)
    compute_factor: Mapped[float] = mapped_column(Float, default=1.0)
    policy_version: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)  # pending|consumed|expired
    consumed_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WorkerCapability(Base):
    """A worker's advertised, validated ability to run a (model_selection,
    execution_profile) on a specific GPU/lease class. Presence is the gate for
    premium admission; a healthy liveness endpoint or raw VRAM is NOT sufficient."""

    __tablename__ = "worker_capabilities"
    __table_args__ = (UniqueConstraint("worker_id", "model_selection", "execution_profile_id", name="uq_workercap_worker_profile"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    worker_id: Mapped[str] = mapped_column(String(120), index=True)
    model_selection: Mapped[str] = mapped_column(String(80), index=True)
    execution_profile_id: Mapped[str] = mapped_column(String(80))
    engine_model: Mapped[str] = mapped_column(String(120))
    planner_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tasks_json: Mapped[list] = mapped_column(JSON, default=list)
    max_duration_seconds: Mapped[int] = mapped_column(Integer, default=600)
    vram_total_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    supports_staged_planner: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
