"""Model capability registry.

Single source of truth for which controls a model release accepts *and* consumes,
their value ranges/defaults/labels, and the generation task types the model can
actually run. The API validates submitted controls against this registry (strict
unknown-control rejection plus value-level and model-applicability checks), and
``GET /models/{id}`` exposes the metadata so the frontend builds/validates its
Advanced control surface from the same source instead of a hand-maintained list.

Pinned upstream evidence: ACE-Step 1.5 commit ca1e85f, release_task_models.
GenerateMusicRequest (see docs/ACE_STEP_CONTROL_PARITY.md). ``shift`` is a
timestep-shift factor that is effective for base checkpoints only; it is marked
base-only here so it is rejected (not silently accepted) on the deployed Turbo
model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

OUTPUT_OPTIONS = ("mix_wav", "mix_mp3", "stems_wav", "stems_zip")


@dataclass(frozen=True)
class ControlSpec:
    key: str
    label: str
    type: str  # "int" | "float" | "str"
    default: Any = None
    min: float | None = None
    max: float | None = None
    max_len: int | None = None
    unit: str = ""
    description: str = ""
    # Families that can actually apply this control. None => all families.
    families: tuple[str, ...] | None = None

    def to_capability(self, applicable: bool) -> dict[str, Any]:
        reason = "" if applicable else "not applicable to this model family"
        return {
            "key": self.key,
            "label": self.label,
            "type": self.type,
            "default": self.default,
            "min": self.min,
            "max": self.max,
            "max_len": self.max_len,
            "unit": self.unit,
            "description": self.description,
            "applicable": applicable,
            "reason": reason,
        }


# key -> spec
CONTROL_SPECS: dict[str, ControlSpec] = {
    spec.key: spec
    for spec in [
        ControlSpec("mood", "Mood", "str", max_len=40,
                    description="Emotional tone folded into the non-lyric caption."),
        ControlSpec("gender", "Lead singer", "str", max_len=20,
                    description="Vocal preference; folded into the caption (no dedicated engine field)."),
        ControlSpec("bpm", "Tempo", "int", min=20, max=300, unit="BPM",
                    description="Beats per minute."),
        ControlSpec("key_scale", "Key", "str", max_len=16,
                    description="Musical key, e.g. 'Amin'."),
        ControlSpec("time_signature", "Time signature", "str", max_len=8,
                    description="Meter, e.g. '4/4'."),
        ControlSpec("vocal_language", "Vocal language", "str", max_len=8,
                    description="Language of sung lyrics (BCP-47-ish code)."),
        ControlSpec("inference_steps", "Quality (steps)", "int", default=8, min=1, max=128,
                    description="Diffusion sampling steps; higher = slower, finer."),
        ControlSpec("guidance_scale", "Guidance", "float", default=7.0, min=0.0, max=20.0,
                    description="CFG strength; how strongly the caption is followed."),
        ControlSpec("shift", "Timestep shift", "float", default=3.0, min=1.0, max=5.0,
                    families=("base",), description="Timestep shift factor; base checkpoints only."),
        ControlSpec("variations", "Variations", "int", default=1, min=1, max=4,
                    description="Number of takes to generate in one batch."),
    ]
}


@dataclass(frozen=True)
class ModelRelease:
    model_id: str
    display_name: str
    revision: str
    enabled: bool
    commercial_policy: str
    license_status: str
    required_notices: tuple[str, ...] = ()
    supported_controls: tuple[str, ...] = ()
    supported_task_types: tuple[str, ...] = ("text2music",)
    model_family: str = "turbo"
    supports_seed: bool = True
    supports_duration: bool = True
    min_duration_seconds: int = 1
    max_duration_seconds: int = 600
    output_options: tuple[str, ...] = OUTPUT_OPTIONS
    capabilities: dict[str, bool] = field(default_factory=dict)


MODEL_RELEASES: dict[str, ModelRelease] = {
    "ace-step-1.5": ModelRelease(
        model_id="ace-step-1.5",
        display_name="ACE-Step 1.5",
        revision="1.5.0@ca1e85f",
        enabled=True,
        commercial_policy="unrestricted",
        license_status="verified",
        # Turbo-applicable controls only (shift is base-only, listed separately
        # in capabilities as not applicable). time_signature now accepted+forwarded.
        supported_controls=(
            "mood", "gender", "bpm", "key_scale", "time_signature", "vocal_language",
            "inference_steps", "guidance_scale", "variations",
        ),
        supported_task_types=("text2music", "cover", "cover-nofsq", "repaint"),
        model_family="turbo",
        min_duration_seconds=10,
        max_duration_seconds=600,
        capabilities={
            "lyrics_conditioned": True,
            "instrumental": True,
            "native_stems": False,
            "fine_tuning": True,
        },
    ),
    "heartmula": ModelRelease(
        model_id="heartmula",
        display_name="HeartMuLa",
        revision="unpinned",
        enabled=False,
        commercial_policy="unrestricted",
        license_status="needs_review",
    ),
    "minimax-music-3": ModelRelease(
        model_id="minimax-music-3",
        display_name="MiniMax Music 3",
        revision="unpinned",
        enabled=False,
        commercial_policy="conditional",
        license_status="needs_review",
    ),
    "diffrhythm-2": ModelRelease(
        model_id="diffrhythm-2",
        display_name="DiffRhythm 2",
        revision="unpinned",
        enabled=False,
        commercial_policy="unrestricted",
        license_status="needs_review",
    ),
    "yue-v1": ModelRelease(
        model_id="yue-v1",
        display_name="YuE v1",
        revision="unpinned",
        enabled=False,
        commercial_policy="unrestricted",
        license_status="needs_review",
    ),
}

SUPPORTED_OPERATIONS = ("music.generate",)


def control_capabilities(model_id: str) -> list[dict[str, Any]]:
    """Every known control, marked applicable or not for this model's family.

    Not-applicable controls stay discoverable (with a reason) rather than
    appearing effective — the parity/UI rule.
    """
    release = MODEL_RELEASES.get(model_id)
    supported = set(release.supported_controls) if release else set()
    return [spec.to_capability(spec.key in supported) for spec in CONTROL_SPECS.values()]


def validate_controls(model_id: str, controls: dict[str, Any]) -> list[dict[str, Any]]:
    """Value-level validation for supported controls. Returns problem records.

    Unknown-control rejection is handled by the caller (CONTROL_UNSUPPORTED);
    this only checks the values of controls the model actually accepts.
    """
    release = MODEL_RELEASES.get(model_id)
    if release is None:
        return []
    problems: list[dict[str, Any]] = []
    allowed = set(release.supported_controls)
    for key, value in (controls or {}).items():
        if key not in allowed:
            continue  # unknown handled elsewhere
        spec = CONTROL_SPECS.get(key)
        if spec is None:
            continue
        problem = _validate_one(spec, value)
        if problem is not None:
            problems.append({"control": key, **problem})
    return problems


def _validate_one(spec: ControlSpec, value: Any) -> dict[str, Any] | None:
    if spec.type == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            return {"code": "CONTROL_TYPE", "message": f"{spec.key} must be an integer.",
                    "allowed": {"type": "int", "min": spec.min, "max": spec.max}}
        if spec.min is not None and value < spec.min or spec.max is not None and value > spec.max:
            return {"code": "CONTROL_RANGE", "message": f"{spec.label} must be between {spec.min} and {spec.max}.",
                    "allowed": {"min": spec.min, "max": spec.max}}
    elif spec.type == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return {"code": "CONTROL_TYPE", "message": f"{spec.key} must be a number.",
                    "allowed": {"type": "float", "min": spec.min, "max": spec.max}}
        f = float(value)
        if spec.min is not None and f < spec.min or spec.max is not None and f > spec.max:
            return {"code": "CONTROL_RANGE", "message": f"{spec.label} must be between {spec.min} and {spec.max}.",
                    "allowed": {"min": spec.min, "max": spec.max}}
    else:  # str
        if not isinstance(value, str):
            return {"code": "CONTROL_TYPE", "message": f"{spec.key} must be a string.",
                    "allowed": {"type": "str", "max_len": spec.max_len}}
        if spec.max_len is not None and len(value) > spec.max_len:
            return {"code": "CONTROL_RANGE", "message": f"{spec.label} is too long (max {spec.max_len} characters).",
                    "allowed": {"max_len": spec.max_len}}
    return None
