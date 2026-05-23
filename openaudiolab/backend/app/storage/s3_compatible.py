import os
from datetime import timedelta
from typing import Optional

from app.storage.base import StorageProvider

try:
    import boto3
    from botocore.exceptions import ClientError
    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False


class S3CompatibleStorageProvider(StorageProvider):
    def __init__(
        self,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str = "us-east-1",
    ):
        self.bucket = bucket
        self.endpoint_url = endpoint_url
        if HAS_BOTO3:
            self.client = boto3.client(
                "s3",
                endpoint_url=endpoint_url,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region,
            )
        else:
            self.client = None

    def upload_file(self, local_path: str, remote_key: str, metadata: Optional[dict] = None) -> bool:
        if not self.client:
            return False
        try:
            extra_args = {}
            if metadata:
                extra_args["Metadata"] = {k: str(v) for k, v in metadata.items()}
            self.client.upload_file(local_path, self.bucket, remote_key.lstrip("/"), ExtraArgs=extra_args)
            return True
        except Exception:
            return False

    def download_file(self, remote_key: str, local_path: str) -> bool:
        if not self.client:
            return False
        try:
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            self.client.download_file(self.bucket, remote_key.lstrip("/"), local_path)
            return True
        except Exception:
            return False

    def generate_signed_download_url(self, remote_key: str, expires_in: int = 3600) -> Optional[str]:
        if not self.client:
            return None
        try:
            url = self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": remote_key.lstrip("/")},
                ExpiresIn=expires_in,
            )
            return url
        except Exception:
            return None

    def delete_file(self, remote_key: str) -> bool:
        if not self.client:
            return False
        try:
            self.client.delete_object(Bucket=self.bucket, Key=remote_key.lstrip("/"))
            return True
        except Exception:
            return False

    def file_exists(self, remote_key: str) -> bool:
        if not self.client:
            return False
        try:
            self.client.head_object(Bucket=self.bucket, Key=remote_key.lstrip("/"))
            return True
        except ClientError:
            return False
