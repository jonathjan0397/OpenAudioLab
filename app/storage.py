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


@dataclass(frozen=True)
class StoredObject:
    body: bytes
    content_range: str | None = None


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
