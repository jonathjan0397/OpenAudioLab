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

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
