import hashlib
import os
import shutil
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote

from app.core.config import settings
from app.storage.base import StorageProvider


class LocalStorageProvider(StorageProvider):
    def __init__(self, base_path: Optional[str] = None):
        self.base_path = base_path or settings.LOCAL_STORAGE_PATH
        os.makedirs(self.base_path, exist_ok=True)

    def _get_full_path(self, remote_key: str) -> str:
        return os.path.join(self.base_path, remote_key.lstrip("/"))

    def upload_file(self, local_path: str, remote_key: str, metadata: Optional[dict] = None) -> bool:
        try:
            full_path = self._get_full_path(remote_key)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            shutil.copy2(local_path, full_path)
            return True
        except Exception:
            return False

    def download_file(self, remote_key: str, local_path: str) -> bool:
        try:
            full_path = self._get_full_path(remote_key)
            if not os.path.exists(full_path):
                return False
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            shutil.copy2(full_path, local_path)
            return True
        except Exception:
            return False

    def generate_signed_download_url(self, remote_key: str, expires_in: int = 3600) -> Optional[str]:
        expires = int(datetime.now(timezone.utc).timestamp()) + expires_in
        safe_key = quote(remote_key, safe="")
        return f"/api/storage/download/{safe_key}?expires={expires}"

    def delete_file(self, remote_key: str) -> bool:
        try:
            full_path = self._get_full_path(remote_key)
            if os.path.exists(full_path):
                os.remove(full_path)
                return True
            return False
        except Exception:
            return False

    def file_exists(self, remote_key: str) -> bool:
        full_path = self._get_full_path(remote_key)
        return os.path.exists(full_path)

    def list_files(self, prefix: str = "") -> list[str]:
        base = self._get_full_path(prefix)
        if not os.path.exists(base):
            return []
        files = []
        for root, dirs, filenames in os.walk(base):
            for f in filenames:
                full = os.path.join(root, f)
                files.append(os.path.relpath(full, self.base_path))
        return files
