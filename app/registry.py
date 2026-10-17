"""Static model-release registry stub (milestone 1).

Pinned upstream revisions and license evidence arrive with milestone 3
(ACE-Step runtime validation). Disabled candidates are listed so discovery
shows them without letting clients queue them as if ready.
"""

from __future__ import annotations

from dataclasses import dataclass, field

OUTPUT_OPTIONS = ("mix_wav", "mix_mp3", "stems_wav", "stems_zip")


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
        supported_controls=("mood",),
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
