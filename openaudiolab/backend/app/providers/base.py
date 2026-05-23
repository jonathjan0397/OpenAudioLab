from abc import ABC, abstractmethod
from typing import Optional


class CloudProvider(ABC):
    @abstractmethod
    def list_available_gpus(self) -> list[dict]:
        pass

    @abstractmethod
    def provision_worker(self, requirements: dict) -> Optional[dict]:
        pass

    @abstractmethod
    def terminate_worker(self, worker_id: str) -> bool:
        pass

    @abstractmethod
    def get_worker_status(self, worker_id: str) -> Optional[dict]:
        pass
