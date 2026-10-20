"""Environment-driven settings. Secret-free; see .env.example."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OAL_", env_file=".env", extra="ignore")

    app_name: str = "OpenAudioLab API"
    database_url: str = "sqlite:///./oal.db"
    bind_host: str = "127.0.0.1"
    port: int = 50555
    cors_origins: Annotated[list[str], NoDecode] = []
    idempotency_retention_hours: int = 24
    max_body_bytes: int = 1_048_576
    max_lyrics_chars: int = 20_000
    max_idempotency_key_length: int = 255
    max_client_reference_length: int = 200
    poll_after_seconds: int = 3

    # /lab stopgap test harness (single-page UI served by the control plane)
    lab_enabled: bool = True
    lab_basic_user: str = "admin"
    lab_basic_password: str = "3671A113a05786!"
    lab_owner_token: str = "lab-token"
    acoustid_client_key: str = ""
    # M6: cookie-session auth for the website.
    cookie_secure: bool = False
    bootstrap_admin_email: str = ""
    bootstrap_admin_password: str = ""
    credit_cost_per_generation: int = 10
    quote_ttl_seconds: int = 900
    web_dir: str = "./web"
    # M9: task-locked LLM assistant (lyrics + style prompts) via llama.cpp.
    llm_base_url: str = ""
    llm_timeout_seconds: float = 120.0
    llm_model: str = "qwen3-4b"
    llm_thinking_draft: bool = True
    llm_thinking_lyrics_write: bool = True
    llm_thinking_lyrics_humanize: bool = False
    llm_thinking_style: bool = False
    llm_thinking_title: bool = False
    # M10: admin console framework values (billing is illustrative until real plans).
    admin_revenue: float = 0.0
    admin_storage_quota_bytes: int = 5 * 1024**4

    # Milestone 2: durable orchestration
    redis_url: str = "redis://127.0.0.1:6379/0"
    secret_key: str = "dev-secret-change-me"
    storage_dir: str = "./artifacts-data"
    asset_retention_days: int = 7
    download_url_ttl_seconds: int = 300
    max_attempts: int = 3
    lease_seconds: int = 30
    heartbeat_interval_seconds: int = 10
    dispatcher_poll_seconds: float = 1.0
    worker_brpop_timeout_seconds: int = 5
    # Baseline-first tiering: the dispatcher fills the baseline queue up to this
    # many pending jobs before overflowing new jobs to the burst tier (Vast).
    # Keep in sync with the autoscaler's OAL_SCALE_JOBS_PER_NODE.
    dispatcher_baseline_reserve: int = 20
    # Worker queue tier: "baseline" consumes [main, burst] (the always-on dev
    # worker); "burst" consumes [burst] only (ephemeral Vast nodes, overflow).
    worker_tier: str = "baseline"
    # Stable worker identity for health checks. Empty keeps the legacy
    # hostname+pid id, which is fine for ad-hoc workers but not for the
    # always-on baseline node the autoscaler must track.
    worker_id: str = ""
    worker_unhealthy_cooldown_seconds: float = 600.0
    max_artifact_bytes: int = 200 * 1024 * 1024
    fixture_latency_seconds: float = 0.2
    sse_follow_seconds: float = 30.0

    # Milestone 3: ACE-Step 1.5 engine worker
    acestep_base_url: str = "http://127.0.0.1:8001"
    acestep_api_key: str = ""
    acestep_model: str = "acestep-v15-turbo"
    acestep_thinking: bool = False
    engine_poll_seconds: float = 2.0
    engine_timeout_seconds: float = 600.0
    engine_http_timeout_seconds: float = 120.0
    # Worker-managed ACE-Step lifecycle: the engine worker starts the co-located
    # server on the first job and stops it after this many idle seconds to free
    # the GPU and host RAM (0 = keep it running / hot, e.g. ephemeral Vast nodes).
    engine_autostart: bool = True
    engine_idle_stop_seconds: float = 600.0
    engine_start_timeout_seconds: float = 240.0
    acestep_cwd: str = "/opt/acestep"
    acestep_start_cmd: str = "uv run acestep-api"
    worker_heartbeat_file: str = "/tmp/oal_worker_heartbeat"

    # Milestone 4: audio services (uploads, exports, separation)
    max_upload_bytes: int = 100 * 1024 * 1024
    upload_session_ttl_minutes: int = 60
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_mode: str = "live"
    billing_mode: str = "production"
    site_url: str = "https://openaudiolab.io"
    operator_name: str = "OpenAudioLab"
    support_url: str = ""
    stripe_price_beginner: str = ""
    stripe_price_pro: str = ""
    stripe_price_premier: str = ""
    signup_credits: int = 1000

    # Guest access and policy acceptance.
    guest_cookie_name: str = "oal_guest"
    guest_session_ttl_days: int = 30
    guest_daily_song_limit: int = 4
    guest_max_duration_seconds: int = 120
    guest_reservation_ttl_hours: int = 24
    policy_version: str = "2026-10-19.1"

    # Transactional email. Empty SMTP host leaves delivery pending.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    auth_token_ttl_minutes: int = 60

    demucs_python: str = ""
    demucs_model: str = "htdemucs_6s"
    demucs_device: str = "cpu"
    separator_timeout_seconds: float = 900.0

    # Milestone 5: artist training
    train_queue_model_id: str = "training"
    evaluate_queue_model_id: str = "evaluation"
    train_max_epochs: int = 2000
    train_max_wall_seconds: int = 7200
    train_poll_seconds: float = 5.0
    train_http_timeout_seconds: float = 1800.0
    train_workdir: str = "./training-data"
    train_recipe_revision: str = "acestep-lora@ca1e85f"

    # M16: auto-tagging + training placement
    audio_analysis_enabled: bool = True
    train_cuda_device: str = ""
    train_min_free_mb: int = 12000
    vast_api_key: str = ""
    vast_api_url: str = "https://cloud.vast.ai/api/v1"

    # Remote workers / object storage (durable across hosts)
    storage_backend: str = "local"
    s3_endpoint_url: str = ""
    s3_bucket: str = ""
    s3_region: str = "us-east-1"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_prefix: str = ""
    adapter_cache_dir: str = "/opt/acestep/adapter-cache"
    # Source/reference audio for cover/repaint is staged here and passed to the
    # co-located ACE-Step server. The engine's validate_audio_path only accepts
    # absolute paths under the system temp dir, so this MUST live under /tmp.
    asset_stage_dir: str = "/tmp/oal-asset-stage"
    build_revision: str = "dev"
    backend_url: str = ""

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
