import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text,
)
from sqlalchemy.orm import relationship

from app.db.base import Base


def _utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    jobs = relationship("GenerationJob", back_populates="user")


class SystemSetting(Base):
    __tablename__ = "system_settings"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    key = Column(String(255), unique=True, nullable=False, index=True)
    value_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class GenerationJob(Base):
    __tablename__ = "generation_jobs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    status = Column(String(50), nullable=False, default="created", index=True)
    prompt = Column(Text, nullable=False)
    genre = Column(String(100), nullable=True)
    mood = Column(String(255), nullable=True)
    lyrics_mode = Column(String(20), nullable=False, default="ai")
    provided_lyrics = Column(Text, nullable=True)
    instrumental = Column(Boolean, default=False, nullable=False)
    duration_seconds = Column(Integer, default=90, nullable=False)
    vocal_mode = Column(String(20), nullable=True, default="male")
    quality = Column(String(20), nullable=False, default="draft")
    dispatch_preference = Column(String(30), nullable=False, default="auto")
    lyric_reasoning_mode = Column(String(20), nullable=True, default="balanced")
    storage_retention_days = Column(Integer, default=7, nullable=False)
    assigned_agent_id = Column(String(36), ForeignKey("agent_nodes.id"), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    expires_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="jobs")
    stages = relationship("JobStage", back_populates="job", cascade="all, delete-orphan")
    assets = relationship("StorageAsset", back_populates="job", cascade="all, delete-orphan")
    assigned_agent = relationship("AgentNode", back_populates="jobs")


class JobStage(Base):
    __tablename__ = "job_stages"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String(36), ForeignKey("generation_jobs.id"), nullable=False, index=True)
    stage_name = Column(String(100), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    job = relationship("GenerationJob", back_populates="stages")


class AgentNode(Base):
    __tablename__ = "agent_nodes"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_name = Column(String(255), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="registering")
    agent_mode = Column(String(30), nullable=False, default="lite")
    hostname = Column(String(255), nullable=True)
    gpu_available = Column(Boolean, default=False, nullable=False)
    gpu_name = Column(String(255), nullable=True)
    vram_gb = Column(Float, default=0.0, nullable=False)
    cuda_available = Column(Boolean, default=False, nullable=False)
    capabilities_json = Column(JSON, nullable=True)
    model_packs_json = Column(JSON, nullable=True)
    container_version = Column(String(20), nullable=True)
    last_heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    draining = Column(Boolean, default=False, nullable=False)
    agent_api_token = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    jobs = relationship("GenerationJob", back_populates="assigned_agent")
    heartbeats = relationship("AgentHeartbeat", back_populates="agent", cascade="all, delete-orphan")


class AgentHeartbeat(Base):
    __tablename__ = "agent_heartbeats"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id = Column(String(36), ForeignKey("agent_nodes.id"), nullable=False, index=True)
    status = Column(String(20), nullable=False)
    active_job_id = Column(String(36), nullable=True)
    gpu_utilization = Column(Float, nullable=True)
    vram_used_gb = Column(Float, nullable=True)
    disk_free_gb = Column(Float, nullable=True)
    container_version = Column(String(20), nullable=True)
    draining = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    agent = relationship("AgentNode", back_populates="heartbeats")


class StorageAsset(Base):
    __tablename__ = "storage_assets"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String(36), ForeignKey("generation_jobs.id"), nullable=False, index=True)
    asset_type = Column(String(50), nullable=False)
    storage_provider = Column(String(30), nullable=False)
    storage_key = Column(String(500), nullable=False)
    filename = Column(String(255), nullable=False)
    mime_type = Column(String(100), nullable=True)
    size_bytes = Column(Integer, nullable=True)
    sha256 = Column(String(64), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    job = relationship("GenerationJob", back_populates="assets")


class ModelRegistryEntry(Base):
    __tablename__ = "model_registry"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    model_id = Column(String(255), unique=True, nullable=False, index=True)
    display_name = Column(String(255), nullable=False)
    engine = Column(String(100), nullable=False)
    task = Column(String(100), nullable=False)
    version = Column(String(100), nullable=False)
    source_url = Column(String(500), nullable=True)
    license = Column(String(255), nullable=True)
    license_url = Column(String(500), nullable=True)
    redistributable_status = Column(String(30), nullable=False, default="needs_review")
    commercial_safe_status = Column(String(30), nullable=False, default="needs_review")
    capabilities_json = Column(JSON, nullable=True)
    min_vram_gb = Column(Integer, default=0, nullable=False)
    recommended_vram_gb = Column(Integer, default=0, nullable=False)
    default_container_policy = Column(String(30), nullable=False, default="mounted")
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
