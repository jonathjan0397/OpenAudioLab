"""Private object storage adapter.

Milestone 2 ships the local-filesystem adapter for single-host Compose and
development. The durable source of truth across hosts will be the
S3-compatible adapter (MinIO locally, managed object storage on the VPS or
cloud); worker code only sees this interface. Server-generated keys only:
clients never submit filesystem paths.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:  # pragma: no cover
    from .config import Settings


@dataclass(frozen=True)
class StoredObject:
    body: bytes
    content_range: str | None = None


class Storage(Protocol):
    """Server-generated keys only; clients never submit filesystem paths."""

    def put(self, key: str, body: bytes) -> str: ...

    def get(self, key: str, byte_range: tuple[int, int] | None = None) -> StoredObject: ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> None: ...

    def list_prefix(self, prefix: str) -> list[str]: ...


class LocalObjectStorage:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not str(path).startswith(str(self.root.resolve())):
            raise ValueError("Storage key escaped the storage root.")
        return path

    def put(self, key: str, body: bytes) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(body)
        tmp.replace(path)
        return hashlib.sha256(body).hexdigest()

    def get(self, key: str, byte_range: tuple[int, int] | None = None) -> StoredObject:
        path = self._path(key)
        body = path.read_bytes()
        if byte_range is None:
            return StoredObject(body=body)
        start, end = byte_range
        start = max(0, start)
        end = min(end, len(body) - 1)
        chunk = body[start : end + 1]
        return StoredObject(body=chunk, content_range=f"bytes {start}-{end}/{len(body)}")

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> None:
        path = self._path(key)
        if path.is_file():
            path.unlink()

    def list_prefix(self, prefix: str) -> list[str]:
        base = (self.root / prefix).resolve()
        root = self.root.resolve()
        if not str(base).startswith(str(root)) or not base.exists():
            return []
        out: list[str] = []
        for p in base.rglob("*"):
            if p.is_file():
                out.append(str(p.relative_to(root)))
        return out


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Parse a single HTTP byte range. Returns None when absent/unsatisfiable-passthrough."""
    if not header or not header.startswith("bytes="):
        return None
    spec = header[6:].split(",")[0].strip()
    if "-" not in spec:
        return None
    start_text, _, end_text = spec.partition("-")
    if start_text == "":
        if end_text == "":
            return None
        suffix = int(end_text)
        if suffix == 0:
            return None
        start = max(0, size - suffix)
        return (start, size - 1)
    start = int(start_text)
    end = int(end_text) if end_text else size - 1
    if start >= size:
        return (start, start)
    return (start, min(end, size - 1))


def asset_blob_keys(storage_key: str) -> list[str]:
    """Object keys backing a single asset row: the file plus any cached peaks JSON."""
    keys = [storage_key]
    if storage_key.endswith(".wav"):
        keys.append(storage_key[: -len(".wav")] + ".json")
    return keys


def delete_asset_blobs(storage: Storage, storage_key: str) -> None:
    """Remove an asset's bytes (and cached waveform) from object storage. Idempotent."""
    for key in asset_blob_keys(storage_key):
        storage.delete(key)


class S3ObjectStorage:
    """S3-compatible adapter (MinIO on the hub, or managed object storage).

    The durable source of truth across hosts: ephemeral workers push results
    here and the API proxies ranged reads, so the bucket stays private.
    """

    def __init__(self, bucket: str, endpoint_url: str | None = None, region: str = "us-east-1",
                 access_key: str | None = None, secret_key: str | None = None, prefix: str = "") -> None:
        import boto3
        from botocore.config import Config

        if not bucket:
            raise ValueError("S3 storage requires a bucket name.")
        self.bucket = bucket
        self.prefix = prefix
        config = Config(s3={"addressing_style": "path"}) if endpoint_url else None
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url or None,
            region_name=region or "us-east-1",
            aws_access_key_id=access_key or None,
            aws_secret_access_key=secret_key or None,
            config=config,
        )

    def _key(self, key: str) -> str:
        return f"{self.prefix}{key}" if self.prefix else key

    def put(self, key: str, body: bytes) -> str:
        self.client.put_object(Bucket=self.bucket, Key=self._key(key), Body=body)
        return hashlib.sha256(body).hexdigest()

    def get(self, key: str, byte_range: tuple[int, int] | None = None) -> StoredObject:
        from botocore.exceptions import ClientError

        kwargs = {"Bucket": self.bucket, "Key": self._key(key)}
        if byte_range is not None:
            start, end = byte_range
            kwargs["Range"] = f"bytes={start}-{end}"
        try:
            response = self.client.get_object(**kwargs)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                raise FileNotFoundError(key) from exc
            raise
        body = response["Body"].read()
        if byte_range is None:
            return StoredObject(body=body)
        content_range = response.get("ContentRange")
        if content_range is None:
            total = self.client.head_object(Bucket=self.bucket, Key=self._key(key))["ContentLength"]
            start, end = byte_range
            content_range = f"bytes {start}-{min(end, total - 1)}/{total}"
        return StoredObject(body=body, content_range=content_range)

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=self._key(key))
            return True
        except ClientError:
            return False

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self._key(key))

    def list_prefix(self, prefix: str) -> list[str]:
        full = self._key(prefix)
        keys: list[str] = []
        token: str | None = None
        while True:
            kwargs = {"Bucket": self.bucket, "Prefix": full, "MaxKeys": 1000}
            if token:
                kwargs["ContinuationToken"] = token
            resp = self.client.list_objects_v2(**kwargs)
            for obj in resp.get("Contents", []):
                k = obj["Key"]
                keys.append(k[len(self.prefix):] if self.prefix and k.startswith(self.prefix) else k)
            if not resp.get("IsTruncated"):
                break
            token = resp.get("NextContinuationToken")
            if not token:
                break
        return keys


def build_storage(settings: "Settings") -> Storage:
    backend = (getattr(settings, "storage_backend", "local") or "local").lower()
    if backend == "s3":
        return S3ObjectStorage(
            bucket=settings.s3_bucket,
            endpoint_url=settings.s3_endpoint_url or None,
            region=settings.s3_region,
            access_key=settings.s3_access_key or None,
            secret_key=settings.s3_secret_key or None,
            prefix=settings.s3_prefix,
        )
    return LocalObjectStorage(settings.storage_dir)
