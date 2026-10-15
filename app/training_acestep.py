"""ACE-Step training adapter (isolated worker side, milestone 5).

Drives the documented upstream training REST surface:
/v1/dataset/scan, /v1/dataset/preprocess, /v1/training/start,
/v1/training/status, /v1/training/stop, /v1/training/export,
/v1/lora/load, /v1/lora/unload. Responses use the same {"code","data"}
envelope as the generation contract.
"""

from __future__ import annotations

from typing import Any

from .engine_acestep import EngineError, HttpTransport


class AceStepTrainingAdapter:
    def __init__(self, transport: HttpTransport) -> None:
        self.transport = transport

    @staticmethod
    def _data(response: dict[str, Any]) -> dict[str, Any]:
        if response.get("code") != 200:
            raise EngineError("ENGINE_REJECTED", str(response.get("error", "training call failed")))
        return response.get("data") or {}

    def ensure_model(self, model: str | None = None) -> dict[str, Any]:
        """The upstream server lazy-loads the DiT; preprocessing needs it."""
        response = self.transport.post_json("/v1/init", {"model": model} if model else {})
        return self._data(response)

    def scan_dataset(self, audio_dir: str, dataset_name: str, all_instrumental: bool = False) -> dict[str, Any]:
        response = self.transport.post_json(
            "/v1/dataset/scan",
            {"audio_dir": audio_dir, "dataset_name": dataset_name, "all_instrumental": all_instrumental},
        )
        return self._data(response)

    def preprocess(self, output_dir: str, skip_existing: bool = False) -> dict[str, Any]:
        response = self.transport.post_json("/v1/dataset/preprocess", {"output_dir": output_dir, "skip_existing": skip_existing})
        return self._data(response)

    def start_training(self, tensor_dir: str, lora_output_dir: str, epochs: int, seed: int,
                       hyperparams: dict[str, Any] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "tensor_dir": tensor_dir,
            "lora_output_dir": lora_output_dir,
            "train_epochs": epochs,
            "training_seed": seed,
        }
        payload.update(hyperparams or {})
        response = self.transport.post_json("/v1/training/start", payload)
        return self._data(response)

    def training_status(self) -> dict[str, Any]:
        raw = self.transport.get_bytes("/v1/training/status")
        import json

        return self._data(json.loads(raw.decode("utf-8")))

    def stop_training(self) -> dict[str, Any]:
        response = self.transport.post_json("/v1/training/stop", {})
        return self._data(response)

    def export(self, lora_output_dir: str, export_path: str) -> dict[str, Any]:
        response = self.transport.post_json(
            "/v1/training/export", {"lora_output_dir": lora_output_dir, "export_path": export_path}
        )
        return self._data(response)

    def load_lora(self, lora_path: str, adapter_name: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"lora_path": lora_path}
        if adapter_name:
            payload["adapter_name"] = adapter_name
        response = self.transport.post_json("/v1/lora/load", payload)
        return self._data(response)

    def unload_lora(self) -> dict[str, Any]:
        response = self.transport.post_json("/v1/lora/unload", {})
        return self._data(response)

    def set_use_lora(self, use_lora: bool) -> dict[str, Any]:
        response = self.transport.post_json("/v1/lora/toggle", {"use_lora": use_lora})
        return self._data(response)
