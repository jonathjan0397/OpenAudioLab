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

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
