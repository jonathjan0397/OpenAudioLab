from typing import Optional

from app.core.config import settings
from app.storage.s3_compatible import S3CompatibleStorageProvider


class MinIOStorageProvider(S3CompatibleStorageProvider):
    def __init__(
        self,
        endpoint_url: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        bucket: Optional[str] = None,
    ):
        super().__init__(
            endpoint_url=endpoint_url or settings.MINIO_ENDPOINT,
            access_key=access_key or settings.MINIO_ACCESS_KEY,
            secret_key=secret_key or settings.MINIO_SECRET_KEY,
            bucket=bucket or settings.MINIO_BUCKET,
        )
