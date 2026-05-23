from abc import ABC, abstractmethod
from typing import Optional


class StorageProvider(ABC):
    @abstractmethod
    def upload_file(self, local_path: str, remote_key: str, metadata: Optional[dict] = None) -> bool:
        pass

    @abstractmethod
    def download_file(self, remote_key: str, local_path: str) -> bool:
        pass

    @abstractmethod
    def generate_signed_download_url(self, remote_key: str, expires_in: int = 3600) -> Optional[str]:
        pass

    @abstractmethod
    def delete_file(self, remote_key: str) -> bool:
        pass

    @abstractmethod
    def file_exists(self, remote_key: str) -> bool:
        pass
