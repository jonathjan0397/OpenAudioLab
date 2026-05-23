from typing import Optional

from app.core.config import settings
from app.providers.base import CloudProvider


class VastAIProvider(CloudProvider):
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.VASTAI_API_KEY or ""

    def list_available_gpus(self) -> list[dict]:
        if not self.api_key or self.api_key == "":
            return []
        return []

    def provision_worker(self, requirements: dict) -> Optional[dict]:
        if not self.api_key or self.api_key == "":
            return None
        return None

    def terminate_worker(self, worker_id: str) -> bool:
        return False

    def get_worker_status(self, worker_id: str) -> Optional[dict]:
        return None
