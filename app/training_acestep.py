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
        """The upstream server lazy-loads the DiT; preprocessing needs it.

        Re-initializing an already-loaded DiT doubles VRAM and OOMs on the
        shared GPU, so probe lora status first (500/404 = not loaded).
        """
        try:
            status = self.transport.get_json("/v1/lora/status")
        except EngineError:
            status = None
        if status is not None and status.get("code") == 200:
            return status.get("data") or {}
        response = self.transport.post_json("/v1/init", {"model": model} if model else {})
        return self._data(response)

    def ensure_llm(self, lm_model_path: str | None = None) -> dict[str, Any]:
        """Initialize the 5Hz LM on the engine (needed by auto_label).

        Probes /health first: a second LLM init would double VRAM on the
        shared GPU.
        """
        try:
            health = self.transport.get_json("/health") or {}
        except EngineError:
            health = {}
        if health.get("llm_initialized"):
            return {"llm_initialized": True}
        payload: dict[str, Any] = {"init_llm": True}
        if lm_model_path:
            payload["lm_model_path"] = lm_model_path
        response = self.transport.post_json("/v1/init", payload)
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

    def auto_label_async(self, *, save_path: str, transcribe_lyrics: bool = True,
                         format_lyrics: bool = True, only_unlabeled: bool = False,
                         skip_metas: bool = False,
                         lm_model_path: str | None = None) -> dict[str, Any]:
        response = self.transport.post_json(
            "/v1/dataset/auto_label_async",
            {"save_path": save_path, "transcribe_lyrics": transcribe_lyrics,
             "format_lyrics": format_lyrics, "only_unlabeled": only_unlabeled,
             "skip_metas": skip_metas, "lm_model_path": lm_model_path},
        )
        return self._data(response)

    def auto_label_status(self, task_id: str) -> dict[str, Any]:
        raw = self.transport.get_json(f"/v1/dataset/auto_label_status/{task_id}") or {}
        if isinstance(raw.get("data"), dict):
            return raw["data"]
        return raw

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

    def set_lora_scale(self, scale: float, adapter_name: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"scale": float(scale)}
        if adapter_name:
            payload["adapter_name"] = adapter_name
        return self._data(self.transport.post_json("/v1/lora/scale", payload))

    def lora_status(self) -> dict[str, Any]:
        raw = self.transport.get_json("/v1/lora/status") or {}
        data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
        return data or {}
