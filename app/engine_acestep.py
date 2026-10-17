"""ACE-Step 1.5 engine adapter (isolated worker side).

Maps OpenAudioLab jobs onto the documented upstream headless REST contract
(/release_task, /query_result, /v1/audio) without assuming any other upstream
behavior. Final lyrics are passed verbatim: lyric rewriting/formatting is
disabled (``use_format=false``) and no lyric LLM runs in this backend.

Pinned runtime evidence (milestone 3, this host):
  upstream commit ca1e85f (2026-08-29), torch 2.10.0+cu128, CUDA 12.8,
  Python 3.12, NVIDIA RTX PRO 4000 Blackwell (sm_120).
  License: MIT code (LICENSE in upstream repo); MIT model card
  https://huggingface.co/ACE-Step/Ace-Step1.5 — checked 2026-10-15.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol


class EngineError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class HttpTransport(Protocol):
    def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]: ...

    def get_bytes(self, path_with_query: str) -> bytes: ...


class RequestsTransport:
    """Default transport using httpx (private upstream URL only)."""

    def __init__(self, base_url: str, api_key: str | None = None, timeout: float = 60.0) -> None:
        import httpx

        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.client = httpx.Client(base_url=base_url, headers=headers, timeout=timeout)

    def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.client.post(path, json=payload)
        _raise_for_status(response.status_code, response)
        return response.json()

    def get_bytes(self, path_with_query: str) -> bytes:
        response = self.client.get(path_with_query)
        _raise_for_status(response.status_code, response)
        return response.content


def _raise_for_status(status: int, response: Any) -> None:
    if status == 200:
        return
    detail = ""
    try:
        detail = str(response.json().get("detail", ""))[:300]
    except Exception:
        pass
    mapping = {
        400: "ENGINE_REJECTED",
        401: "ENGINE_AUTH",
        404: "ENGINE_NOT_FOUND",
        429: "ENGINE_BUSY",
    }
    code = mapping.get(status, "ENGINE_UNAVAILABLE" if status >= 500 else "ENGINE_ERROR")
    raise EngineError(code, detail or f"Upstream returned HTTP {status}.")


@dataclass(frozen=True)
class SubmitResult:
    task_id: str


class AceStepAdapter:
    """Generic internal contract over the documented ACE-Step HTTP API."""

    ENGINE_NAME = "ace-step-1.5"

    def __init__(
        self,
        transport: HttpTransport,
        model: str = "acestep-v15-turbo",
        thinking: bool = False,
    ) -> None:
        self.transport = transport
        self.model = model
        self.thinking = thinking

    # -- capability/discovery -------------------------------------------------

    def health(self) -> bool:
        try:
            return bool(self.transport.get_bytes("/health"))
        except EngineError:
            return False

    def list_models(self) -> list[str]:
        response = self._get_json("/v1/models")
        return [item["name"] for item in response.get("data", {}).get("models", [])]

    def _get_json(self, path: str) -> dict[str, Any]:
        raw = self.transport.get_bytes(path)
        return json.loads(raw.decode("utf-8"))

    # -- request mapping ------------------------------------------------------

    def build_payload(
        self,
        music_description: str,
        lyrics: str | None,
        instrumental: bool,
        seed: int | None,
        duration_seconds: int | None,
        controls: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        controls = controls or {}
        payload: dict[str, Any] = {
            "prompt": music_description,
            "lyrics": "" if instrumental or lyrics is None else lyrics,
            "audio_format": "wav",
            "batch_size": 1,
            "thinking": self.thinking,
            # Never let the upstream LM rewrite or reformat approved lyrics.
            "use_format": False,
            "model": self.model,
        }
        # M14c advanced controls (HTTP names per release_task_models).
        if controls.get("bpm"):
            payload["bpm"] = int(controls["bpm"])
        if controls.get("key_scale"):
            payload["key_scale"] = str(controls["key_scale"])
        if controls.get("vocal_language"):
            payload["vocal_language"] = str(controls["vocal_language"])
        if controls.get("inference_steps"):
            payload["inference_steps"] = int(controls["inference_steps"])
        if controls.get("guidance_scale"):
            payload["guidance_scale"] = float(controls["guidance_scale"])
        if controls.get("shift"):
            payload["shift"] = float(controls["shift"])
        if controls.get("variations"):
            payload["batch_size"] = max(1, min(4, int(controls["variations"])))
        if seed is not None:
            payload["use_random_seed"] = False
            payload["seed"] = seed
        else:
            payload["use_random_seed"] = True
        if duration_seconds is not None:
            payload["audio_duration"] = float(duration_seconds)
        if not self.thinking:
            # Avoid implicit 5Hz LM metadata calls when running DiT-only.
            payload["use_cot_caption"] = False
            payload["use_cot_language"] = False
        return payload

    # -- async job lifecycle ----------------------------------------------------

    def submit(self, payload: dict[str, Any]) -> SubmitResult:
        response = self.transport.post_json("/release_task", payload)
        if response.get("code") != 200:
            raise EngineError("ENGINE_REJECTED", str(response.get("error", "submit failed")))
        data = response.get("data") or {}
        task_id = data.get("task_id")
        if not task_id:
            raise EngineError("ENGINE_ERROR", "Upstream submit returned no task_id.")
        return SubmitResult(task_id=task_id)

    def poll(self, task_id: str) -> tuple[str, list[dict[str, Any]] | None]:
        """Return (pending|succeeded|failed, parsed result entries or None)."""
        response = self.transport.post_json("/query_result", {"task_id_list": [task_id]})
        entries = response.get("data") or []
        if not entries:
            raise EngineError("ENGINE_NOT_FOUND", f"Unknown upstream task {task_id}.")
        entry = entries[0]
        status = entry.get("status")
        if status == 1:
            raw = entry.get("result")
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            items = parsed if isinstance(parsed, list) else [parsed]
            return "succeeded", [i for i in items if isinstance(i, dict)]
        if status == 2:
            return "failed", None
        return "pending", None

    def download(self, file_url: str) -> bytes:
        # ``file`` values are /v1/audio?path=... URLs relative to the server.
        return self.transport.get_bytes(file_url)

    # -- trained adapter (milestone 5) -------------------------------------------

    def ensure_model(self) -> None:
        """Initialize the DiT if the server lazy-loaded it away (needed before LoRA load)."""
        response = self.transport.post_json("/v1/init", {})
        if response.get("code") != 200:
            raise EngineError("ENGINE_REJECTED", str(response.get("error", "model init failed")))

    def load_lora(self, lora_path: str, adapter_name: str | None = None) -> None:
        payload: dict[str, Any] = {"lora_path": lora_path}
        if adapter_name:
            payload["adapter_name"] = adapter_name
        response = self.transport.post_json("/v1/lora/load", payload)
        if response.get("code") != 200:
            raise EngineError("ENGINE_REJECTED", str(response.get("error", "lora load failed")))

    def unload_lora(self) -> None:
        response = self.transport.post_json("/v1/lora/unload", {})
        if response.get("code") != 200:
            raise EngineError("ENGINE_REJECTED", str(response.get("error", "lora unload failed")))

    @property
    def upstream_termination_supported(self) -> bool:
        # The reviewed REST contract exposes no task cancellation endpoint;
        # remote cancellation can only discard late results.
        return False
