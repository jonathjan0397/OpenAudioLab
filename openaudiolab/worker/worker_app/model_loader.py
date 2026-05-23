import logging
from typing import Optional

logger = logging.getLogger("worker.model_loader")


class ModelLoader:
    @staticmethod
    def load_model(model_id: str, model_path: str) -> Optional[object]:
        logger.info(f"Loading model {model_id} from {model_path}")
        return None

    @staticmethod
    def unload_model(model_id: str) -> bool:
        logger.info(f"Unloading model {model_id}")
        return True

    @staticmethod
    def get_loaded_models() -> list[str]:
        return []
