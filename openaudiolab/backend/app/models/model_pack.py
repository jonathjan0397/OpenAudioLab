import json
import os
from typing import Optional


class ModelPack:
    def __init__(self, manifest_path: str):
        self.manifest_path = manifest_path
        self.manifest = self._load_manifest()

    def _load_manifest(self) -> dict:
        if not os.path.exists(self.manifest_path):
            return {}
        with open(self.manifest_path, "r") as f:
            return json.load(f)

    @property
    def pack_id(self) -> str:
        return self.manifest.get("model_pack_id", "")

    @property
    def display_name(self) -> str:
        return self.manifest.get("display_name", "")

    @property
    def description(self) -> str:
        return self.manifest.get("description", "")

    @property
    def models(self) -> list[dict]:
        return self.manifest.get("models", [])

    def get_model_by_task(self, task: str) -> Optional[dict]:
        for model in self.models:
            if model.get("task") == task:
                return model
        return None

    def get_model_by_id(self, model_id: str) -> Optional[dict]:
        for model in self.models:
            if model.get("id") == model_id:
                return model
        return None

    def has_capability(self, task: str) -> bool:
        return self.get_model_by_task(task) is not None

    def validate(self) -> list[str]:
        errors = []
        if not self.pack_id:
            errors.append("Missing model_pack_id")
        if not self.display_name:
            errors.append("Missing display_name")
        if not self.models:
            errors.append("No models defined")
        for model in self.models:
            if not model.get("id"):
                errors.append(f"Model missing id in pack {self.pack_id}")
            if not model.get("task"):
                errors.append(f"Model {model.get('id')} missing task")
        return errors
