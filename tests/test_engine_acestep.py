from __future__ import annotations

import json

import pytest

from app.engine_acestep import AceStepAdapter, EngineError


class FakeTransport:
    def __init__(self, responses: list[tuple[int, object]]) -> None:
        self.responses = responses
        self.posted: list[tuple[str, dict]] = []
        self.got: list[str] = []

    def post_json(self, path: str, payload: dict) -> dict:
        self.posted.append((path, payload))
        status, body = self.responses.pop(0)
        if status != 200:
            raise EngineError("ENGINE_REJECTED", f"HTTP {status}")
        return body

    def get_json(self, path: str) -> dict | None:
        self.got.append(path)
        status, body = self.responses[0]
        if status == 404:
            self.responses.pop(0)
            return None
        return body if isinstance(body, dict) else None

    def get_bytes(self, path: str) -> bytes:
        self.got.append(path)
        status, body = self.responses.pop(0)
        if status != 200:
            raise EngineError("ENGINE_UNAVAILABLE", f"HTTP {status}")
        return body if isinstance(body, bytes) else json.dumps(body).encode()


def test_payload_passes_lyrics_verbatim() -> None:
    transport = FakeTransport([])
    adapter = AceStepAdapter(transport)
    payload = adapter.build_payload(
        music_description="Acoustic country.",
        lyrics="  Morning émoji 🎵\r\npine\n",
        instrumental=False,
        seed=7,
        duration_seconds=120,
    )
    assert payload["lyrics"] == "  Morning émoji 🎵\r\npine\n"
    assert payload["use_format"] is False
    assert payload["audio_format"] == "wav"
    assert payload["batch_size"] == 1
    assert payload["use_random_seed"] is False
    assert payload["seed"] == 7
    assert payload["audio_duration"] == 120.0
    assert payload["model"] == "acestep-v15-turbo"


def test_payload_instrumental_and_random_seed() -> None:
    adapter = AceStepAdapter(FakeTransport([]))
    payload = adapter.build_payload("drums only", None, True, None, None)
    assert payload["lyrics"] == ""
    assert payload["use_random_seed"] is True
    assert "seed" not in payload
    assert "audio_duration" not in payload


def test_submit_and_poll_lifecycle() -> None:
    transport = FakeTransport(
        [
            (200, {"code": 200, "data": {"task_id": "t-1"}}),
            (200, {"code": 200, "data": [{"task_id": "t-1", "status": 0}]}),
            (200, {"code": 200, "data": [{"task_id": "t-1", "status": 1, "result": json.dumps([{"file": "/v1/audio?path=%2Ftmp%2Fa.wav", "dit_model": "acestep-v15-turbo"}])}]}),
            (200, {"code": 200, "data": [{"task_id": "t-1", "status": 2}]}),
        ]
    )
    adapter = AceStepAdapter(transport)
    submit = adapter.submit({"prompt": "x"})
    assert submit.task_id == "t-1"
    assert transport.posted[0][0] == "/release_task"

    state, _ = adapter.poll("t-1")
    assert state == "pending"
    state, result = adapter.poll("t-1")
    assert state == "succeeded"
    assert result[0]["file"] == "/v1/audio?path=%2Ftmp%2Fa.wav"
    state, _ = adapter.poll("t-1")
    assert state == "failed"


def test_poll_unknown_task_raises() -> None:
    transport = FakeTransport([(200, {"code": 200, "data": []})])
    adapter = AceStepAdapter(transport)
    with pytest.raises(EngineError) as exc:
        adapter.poll("missing")
    assert exc.value.code == "ENGINE_NOT_FOUND"


def test_download_uses_relative_audio_url() -> None:
    transport = FakeTransport([(200, b"RIFF....WAVE")])
    adapter = AceStepAdapter(transport)
    body = adapter.download("/v1/audio?path=%2Ftmp%2Fa.wav")
    assert body == b"RIFF....WAVE"
    assert transport.got == ["/v1/audio?path=%2Ftmp%2Fa.wav"]


def test_upstream_termination_not_supported() -> None:
    assert AceStepAdapter(FakeTransport([])).upstream_termination_supported is False


def test_payload_cot_planner_forwards_thinking_and_lm_path() -> None:
    transport = FakeTransport([])
    adapter = AceStepAdapter(transport)  # self.thinking default False
    payload = adapter.build_payload(
        music_description="Contemporary country.", lyrics="verse one\nline two",
        instrumental=False, seed=7, duration_seconds=240,
        controls={"inference_steps": 100, "guidance_scale": 7.0, "shift": 3.0, "use_adg": True},
        thinking=True, lm_model_path="acestep-5Hz-lm-1.7B",
    )
    assert payload["thinking"] is True
    assert payload["lm_model_path"] == "acestep-5Hz-lm-1.7B"
    assert payload["use_adg"] is True
    assert payload["use_format"] is False          # verbatim lyrics: never reformat
    assert "use_cot_caption" not in payload         # CoT left to engine default (True)
    assert payload["lyrics"] == "verse one\nline two"


def test_payload_dit_only_disables_cot_and_thinking() -> None:
    transport = FakeTransport([])
    adapter = AceStepAdapter(transport)
    payload = adapter.build_payload(
        music_description="x", lyrics=None, instrumental=True, seed=None,
        duration_seconds=12, controls={"inference_steps": 8}, thinking=False,
    )
    assert payload["thinking"] is False
    assert payload["use_cot_caption"] is False      # DiT-only path
    assert payload["use_cot_language"] is False
    assert "lm_model_path" not in payload
    assert "use_adg" not in payload


def test_payload_folds_style_caption_into_prompt() -> None:
    adapter = AceStepAdapter(FakeTransport([]))
    payload = adapter.build_payload("spacey synth led", None, True, None, 60,
                                    style="dream pop, hazy synths")
    assert payload["prompt"] == "spacey synth led, dream pop, hazy synths"
    assert payload["lyrics"] == ""


def test_payload_without_style_is_unchanged() -> None:
    adapter = AceStepAdapter(FakeTransport([]))
    plain = adapter.build_payload("x", None, True, None, None)
    explicit_none = adapter.build_payload("x", None, True, None, None, style=None)
    assert plain == explicit_none
    assert plain["prompt"] == "x"


def test_payload_style_trimmed_to_caption_budget() -> None:
    adapter = AceStepAdapter(FakeTransport([]))
    payload = adapter.build_payload("d" * 1990, None, True, None, None,
                                    style="e" * 500)
    assert payload["prompt"] == ("d" * 1990 + ", " + "e" * 500)[:2000]
