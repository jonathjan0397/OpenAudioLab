from datetime import datetime, timedelta, timezone
from typing import Optional

from app.core.config import settings
from app.storage.base import StorageProvider
from app.storage.local import LocalStorageProvider
from app.storage.minio import MinIOStorageProvider
from app.storage.s3_compatible import S3CompatibleStorageProvider


class StorageService:
    _instance = None
    _provider: Optional[StorageProvider] = None

    @classmethod
    def get_provider(cls) -> StorageProvider:
        if cls._provider is None:
            cls._provider = cls._create_provider()
        return cls._provider

    @classmethod
    def _create_provider(cls) -> StorageProvider:
        provider_type = settings.STORAGE_PROVIDER.lower()
        if provider_type == "local":
            return LocalStorageProvider()
        elif provider_type == "minio":
            return MinIOStorageProvider()
        elif provider_type in ("s3", "s3_compatible"):
            return S3CompatibleStorageProvider(
                endpoint_url=settings.MINIO_ENDPOINT,
                access_key=settings.MINIO_ACCESS_KEY,
                secret_key=settings.MINIO_SECRET_KEY,
                bucket=settings.MINIO_BUCKET,
            )
        else:
            return LocalStorageProvider()

    @classmethod
    def upload_file(cls, local_path: str, remote_key: str, metadata: Optional[dict] = None) -> bool:
        return cls.get_provider().upload_file(local_path, remote_key, metadata)

    @classmethod
    def download_file(cls, remote_key: str, local_path: str) -> bool:
        return cls.get_provider().download_file(remote_key, local_path)

    @classmethod
    def generate_signed_url(cls, remote_key: str, expires_in: int = 3600) -> Optional[str]:
        return cls.get_provider().generate_signed_download_url(remote_key, expires_in)

    @classmethod
    def delete_file(cls, remote_key: str) -> bool:
        return cls.get_provider().delete_file(remote_key)

    @classmethod
    def file_exists(cls, remote_key: str) -> bool:
        return cls.get_provider().file_exists(remote_key)

    @classmethod
    def get_job_storage_key(cls, job_id: str, subpath: str) -> str:
        return f"/jobs/{job_id}/{subpath.lstrip('/')}"

    @classmethod
    def get_retention_expires_at(cls, retention_days: Optional[int] = None) -> datetime:
        days = retention_days or settings.DEFAULT_RETENTION_DAYS
        return datetime.now(timezone.utc) + timedelta(days=days)
