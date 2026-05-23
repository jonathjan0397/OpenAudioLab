import os
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    APP_ENV: str = "development"
    BACKEND_PORT: int = 8000
    FRONTEND_PORT: int = 5173

    DATABASE_URL: str = "postgresql://openaudiolab:openaudiolab@postgres:5432/openaudiolab"
    REDIS_URL: str = "redis://redis:6379/0"

    SECRET_KEY: str = "change-this-before-production"
    JWT_SECRET: str = "change-this-before-production"
    CORS_ALLOWED_ORIGINS: str = "http://localhost:5173"

    STORAGE_PROVIDER: str = "local"
    LOCAL_STORAGE_PATH: str = "/data/openaudiolab/storage"
    DEFAULT_RETENTION_DAYS: int = 7

    MINIO_ENDPOINT: str = "http://minio:9000"
    MINIO_ACCESS_KEY: str = "openaudiolab"
    MINIO_SECRET_KEY: str = "openaudiolab-secret"
    MINIO_BUCKET: str = "openaudiolab-jobs"

    WORKER_REGISTRATION_TOKEN: str = "change-this-worker-token"
    WORKER_VERSION: str = "0.1.0"
    WORKER_MODE: str = "lite"

    ENABLE_CPU_TEST_GENERATION: bool = True
    CPU_TEST_MAX_DURATION_SECONDS: int = 15

    SEED_DEV_ADMIN: bool = False

    RUNPOD_API_KEY: Optional[str] = None
    VASTAI_API_KEY: Optional[str] = None
    ENABLE_CLOUD_WORKERS: bool = False

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ALLOWED_ORIGINS.split(",") if origin.strip()]

    def validate_production_secrets(self) -> list[str]:
        warnings = []
        if self.is_production:
            if self.SECRET_KEY == "change-this-before-production":
                warnings.append("SECRET_KEY is using default value")
            if self.JWT_SECRET == "change-this-before-production":
                warnings.append("JWT_SECRET is using default value")
            if self.WORKER_REGISTRATION_TOKEN == "change-this-worker-token":
                warnings.append("WORKER_REGISTRATION_TOKEN is using default value")
            if self.STORAGE_PROVIDER != "local":
                if not self.MINIO_ACCESS_KEY or self.MINIO_ACCESS_KEY == "openaudiolab":
                    warnings.append("Storage credentials may be missing for cloud storage")
        return warnings

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


settings = Settings()
