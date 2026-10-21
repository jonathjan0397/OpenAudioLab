"""Multi-model catalog: public selections -> engine releases, execution profiles,
and a versioned credit price policy with quote computation.

This is configuration, not live proof: a profile is only *admissible* when its
release is `available` AND a worker has advertised the matching capability
(Stage E). Premium checkpoints that are not provisioned stay `unconfigured`, so
admission returns 503 rather than silently downgrading to Turbo.

Grounded against the pinned engine (ca1e85f):
- Turbo's handler makes CFG effective 1.0 (guidance>1 enables CFG); the
  `turbo-fast-v1` profile therefore locks steps=8 and guidance=1.0.
- SFT/Base are separate families; SFT defaults DCW off (model-aware upstream
  default); the pinned REST has no `sampler_mode`, so euler/heun/ancestral are
  rejected, and `timesteps` overrides steps (effective NFE is counted).
- Denoising defaults follow upstream per-model recommendations (not the low
  initial values). Non-turbo (sft/xl-sft/merge): steps 64/100/64, guidance 7.0
  (band 5.0-9.0; upstream default 7.0, "typical 5-9", best-quality 7-9), shift
  1.0, DCW off. Turbo-family (turbo/xl-turbo) is CFG-distilled: steps 8 +
  guidance 1.0 locked, shift 3.0, DCW on (turbo default). `shift` is a
  profile-owned band so it is exempt from the registry's base-only marker.
- XL (4B) DiT models are first-class in the pinned runtime (upstream issue #990,
  PR #989, merged before ca1e85f). The 4B DiT is ~9 GB bf16 resident, but the
  full engine (DiT + Qwen3-0.6B text encoder [1.2 GB] + VAE + activations) peaks
  ~20.6 GiB WITHOUT offload, which OOMs a 24 GB card beside a GPU-resident
  llama-server (the "XL fits without offload" tier6b note was wrong for the full
  process). The worker therefore runs `ACESTEP_OFFLOAD_TO_CPU=1` + int8 weight-only
  DiT (`ACESTEP_QUANTIZATION=int8_weight_only`, halving the resident DiT), holding
  a measured steady ~13.5 GB so XL-Turbo/XL-SFT serve alongside the lyrics
  llama-server still on GPU (same 15 GB VRAM floor below).
- The community merge stays unconfigured until its exact checkpoint/license/VRAM
  are approved and benchmarked.

Multipliers are PROVISIONAL starting values (not measured tariffs); Turbo stays
at the existing base charge (multiplier 1.0).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from .registry import CONTROL_SPECS

# Versioned so quotes/jobs can be revalidated if pricing changes.
PRICE_POLICY_VERSION = "credits-2026-10-20.1"
# Compute factor default is provisional (>=1 relative to a profile's standard
# preset). Real benchmarks would refine it; a heavy request can't pay the base.
DEFAULT_COMPUTE_FACTOR = 1.0


@dataclass(frozen=True)
class ExecutionProfile:
    profile_id: str
    model_selection: str
    engine_model: str  # checkpoint name in the worker image
    native_family: str  # turbo | sft | xl | merge
    label: str
    quality_note: str
    steps_min: int
    steps_max: int
    steps_default: int
    cfg_min: float
    cfg_max: float
    cfg_default: float
    cfg_locked: bool  # when True, guidance is fixed and not user-tunable
    dcw_forced_off: bool
    planner_model: str | None
    tasks: tuple[str, ...]
    max_duration_seconds: int
    max_batch: int
    availability: str  # available | unconfigured | disabled
    multiplier: float
    compute_factor: float = DEFAULT_COMPUTE_FACTOR
    sampler_modes: tuple[str, ...] = ("ode", "sde")
    # Minimum GPU VRAM (MB) a worker must have to run this profile. Registration
    # only advertises a premium profile on workers that actually fit it -- a
    # healthy liveness endpoint or total VRAM is not the test; this is. XL (4B
    # DiT) loads ~9 GB bf16 and is an upstream 20-24 GB (tier6b) model, so the
    # floor (15 GB) lets the shared 24 GB baseline worker serve it once the
    # llama-server footprint is shrunk (OAL_LLM_CTX/OAL_LLM_GPU_LAYERS).
    vram_required_mb: int = 0
    # Timestep-shift band the profile exposes to the DiT. Effective for the base
    # family (sft/xl/merge); turbo-family distills a discrete {1,2,3} schedule and
    # defaults to 3.0. Profile owns the band so it is exempt from the registry's
    # base-only applicability marker (see validate_profile_controls).
    shift_min: float = 1.0
    shift_max: float = 5.0
    shift_default: float = 1.0
    # Run the 5 Hz lyric-LM planner (CoT audio-code blueprint). Premium (SFT/XL)
    # needs it for coherent vocal/long audio; DiT-only turbo stays fast. Backed by
    # planner_model (which LM to load). Without it the DiT gets only text conditioning
    # and long renders collapse into a noise wash (engine issue #929).
    use_cot: bool = False
    # use_adg (Adaptive Dual Guidance) default -- base/SFT quality knob (turbo ignores it).
    adg_default: bool = False

    def control_schema(self) -> dict[str, Any]:
        steps: dict[str, Any] = {"type": "integer", "minimum": self.steps_min, "maximum": self.steps_max}
        if self.cfg_locked:
            steps["const"] = self.steps_default
        return {
            "profile_id": self.profile_id,
            "inference_steps": steps,
            "guidance_scale": {
                "type": "number",
                "minimum": self.cfg_min,
                "maximum": self.cfg_max,
                **({"const": self.cfg_default} if self.cfg_locked else {}),
                "locked": self.cfg_locked,
            },
            "dcw_enabled": {"type": "boolean", "const": False} if self.dcw_forced_off else {"type": "boolean"},
            "infer_method": {"type": "string", "enum": list(self.sampler_modes)},
            "shift": {
                "type": "number",
                "minimum": self.shift_min,
                "maximum": self.shift_max,
                "default": self.shift_default,
            },
            "tasks": list(self.tasks),
            "max_duration_seconds": self.max_duration_seconds,
            "max_batch": self.max_batch,
        }


@dataclass(frozen=True)
class ModelRelease:
    selection: str
    display_name: str
    family: str
    license_status: str
    profiles: tuple[ExecutionProfile, ...]
    experimental: bool = False

    @property
    def engine_model(self) -> str:
        return self.profiles[0].engine_model

    @property
    def availability(self) -> str:
        # A release is only as available as its most-available profile.
        order = {"available": 0, "unconfigured": 1, "disabled": 2}
        return sorted((p.availability for p in self.profiles), key=lambda a: order.get(a, 9))[0]

    def profile(self, profile_id: str) -> ExecutionProfile | None:
        return next((p for p in self.profiles if p.profile_id == profile_id), None)


def _turbo() -> ModelRelease:
    return ModelRelease(
        selection="ace-step-1.5-turbo",
        display_name="ACE-Step 1.5 Turbo",
        family="turbo",
        license_status="verified",
        profiles=(
            ExecutionProfile(
                profile_id="turbo-fast-v1",
                model_selection="ace-step-1.5-turbo",
                engine_model="acestep-v15-turbo",
                native_family="turbo",
                label="Fast",
                quality_note="8 steps, effective CFG 1.0; fastest, lowest VRAM.",
                steps_min=8, steps_max=8, steps_default=8,
                cfg_min=1.0, cfg_max=1.0, cfg_default=1.0, cfg_locked=True,
                dcw_forced_off=False,  # model-aware default; Turbo verified default preserved
                planner_model="acestep-5Hz-lm-1.7B",
                tasks=("text2music", "cover", "cover-nofsq", "repaint"),
                max_duration_seconds=600, max_batch=4,
                availability="available", multiplier=1.00,
                vram_required_mb=14000,
                shift_min=1.0, shift_max=3.0, shift_default=3.0,
            ),
        ),
    )


def _sft() -> ModelRelease:
    return ModelRelease(
        selection="ace-step-1.5-sft",
        display_name="ACE-Step 1.5 SFT",
        family="sft",
        license_status="verified",
        profiles=(
            ExecutionProfile(
                profile_id="sft-quality-v1",
                model_selection="ace-step-1.5-sft",
                engine_model="acestep-v15-sft",
                native_family="sft",
                label="Quality",
                quality_note="64 steps (50-100), CFG 7.0 (5-9), DCW off, shift 3.0, ADG + 5Hz-LM planner (coherent vocals/long).",
                steps_min=50, steps_max=100, steps_default=64,
                cfg_min=5.0, cfg_max=9.0, cfg_default=7.0, cfg_locked=False,
                dcw_forced_off=True,
                planner_model="acestep-5Hz-lm-1.7B",
                tasks=("text2music", "cover", "cover-nofsq", "repaint"),
                max_duration_seconds=600, max_batch=2,
                availability="available", multiplier=2.00,
                vram_required_mb=15000,
                shift_min=1.0, shift_max=3.0, shift_default=3.0,
                use_cot=True, adg_default=True,
            ),
        ),
    )


def _xl() -> ModelRelease:
    from .config import get_settings

    ckpt = (get_settings().xl_checkpoint_id or "").strip()
    return ModelRelease(
        selection="ace-step-1.5-xl-sft",
        display_name="ACE-Step 1.5 XL SFT (premium)",
        family="xl",
        license_status="verified",
        profiles=(
            ExecutionProfile(
                profile_id="xl-sft-quality-v1",
                model_selection="ace-step-1.5-xl-sft",
                engine_model=ckpt or "acestep-v15-xl-sft",
                native_family="xl",
                label="Premium (XL 4B DiT)",
                quality_note="XL 4B DiT (SFT); 100 steps, CFG 7.0 (5-9), DCW off, shift 3.0, ADG + 5Hz-LM planner. bf16 on a 24 GB worker (drafting LLM off-card).",
                steps_min=50, steps_max=100, steps_default=100,
                cfg_min=5.0, cfg_max=9.0, cfg_default=7.0, cfg_locked=False,
                dcw_forced_off=True,
                planner_model="acestep-5Hz-lm-1.7B",
                tasks=("text2music", "cover", "repaint"),
                max_duration_seconds=600, max_batch=1,
                availability="available" if ckpt else "unconfigured", multiplier=4.00,
                vram_required_mb=15000,
                shift_min=1.0, shift_max=3.0, shift_default=3.0,
                use_cot=True, adg_default=True,
            ),
        ),
    )


def _xl_turbo() -> ModelRelease:
    from .config import get_settings

    ckpt = (get_settings().xl_turbo_checkpoint_id or "").strip()
    return ModelRelease(
        selection="ace-step-1.5-xl-turbo",
        display_name="ACE-Step 1.5 XL Turbo (premium)",
        family="xl",
        license_status="verified",
        profiles=(
            ExecutionProfile(
                profile_id="xl-turbo-fast-v1",
                model_selection="ace-step-1.5-xl-turbo",
                engine_model=ckpt or "acestep-v15-xl-turbo",
                native_family="xl",
                label="Fast (XL 4B DiT)",
                quality_note="XL 4B DiT (Turbo); CFG-distilled, 8 steps, DCW on, shift 3.0, 5Hz-LM planner. Fast, higher fidelity than 2B turbo.",
                steps_min=8, steps_max=8, steps_default=8,
                cfg_min=1.0, cfg_max=1.0, cfg_default=1.0, cfg_locked=True,
                dcw_forced_off=False,  # turbo-family distillation default (DCW on), matches 2B turbo
                planner_model="acestep-5Hz-lm-1.7B",
                tasks=("text2music", "cover", "repaint"),
                max_duration_seconds=600, max_batch=1,
                availability="available" if ckpt else "unconfigured", multiplier=2.00,
                vram_required_mb=15000,
                shift_min=1.0, shift_max=3.0, shift_default=3.0,
                use_cot=True, adg_default=False,
            ),
        ),
    )


def _merge() -> ModelRelease:
    from .config import get_settings

    ckpt = (get_settings().merge_checkpoint_id or "").strip()
    return ModelRelease(
        selection="ace-step-1.5-merge-sft-turbo",
        display_name="ACE-Step 1.5 Merge SFT+Turbo (experimental)",
        family="merge",
        license_status="unverified",
        experimental=True,
        profiles=(
            ExecutionProfile(
                profile_id="merge-experimental-v1",
                model_selection="ace-step-1.5-merge-sft-turbo",
                engine_model=ckpt,
                native_family="merge",
                label="Experimental merge",
                quality_note="Operator-provided community checkpoint; may produce composition artifacts. "
                             "Set OAL_MERGE_CHECKPOINT_ID after validating exact repo/revision/license/VRAM.",
                steps_min=50, steps_max=100, steps_default=64,
                cfg_min=5.0, cfg_max=9.0, cfg_default=7.0, cfg_locked=False,
                dcw_forced_off=True,
                planner_model="acestep-5Hz-lm-1.7B",
                tasks=("text2music",) if ckpt else (),
                max_duration_seconds=600, max_batch=1,
                availability="available" if ckpt else "unconfigured", multiplier=1.50,
                vram_required_mb=16000,
                shift_min=1.0, shift_max=3.0, shift_default=3.0,
                use_cot=True, adg_default=True,
            ),
        ),
    )


CATALOG: dict[str, ModelRelease] = {
    r.selection: r for r in (_turbo(), _sft(), _xl(), _xl_turbo(), _merge())
}

# Legacy model_id -> turbo profile (existing behavior preserved).
LEGACY_MODEL_ID_MAP = {"ace-step-1.5": ("ace-step-1.5-turbo", "turbo-fast-v1")}


class CatalogError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


def resolve(model_selection: str | None, execution_profile_id: str | None, legacy_model_id: str | None):
    """Resolve to (release, profile). Rejects contradictions; never downgrades."""
    if model_selection is None and execution_profile_id is None:
        if legacy_model_id is None:
            raise CatalogError(422, "MODEL_SELECTION_REQUIRED", "Provide model_selection or model_id.")
        if legacy_model_id not in LEGACY_MODEL_ID_MAP:
            raise CatalogError(422, "MODEL_UNKNOWN", "Unknown model_id.", {"known": [*LEGACY_MODEL_ID_MAP, *CATALOG]})
        selection, profile_id = LEGACY_MODEL_ID_MAP[legacy_model_id]
    else:
        selection = model_selection
        profile_id = execution_profile_id
        # If both model_id and model_selection are present they must agree.
        if legacy_model_id is not None:
            mapped = LEGACY_MODEL_ID_MAP.get(legacy_model_id)
            if mapped and mapped[0] != selection:
                raise CatalogError(
                    422, "MODEL_SELECTION_CONFLICT",
                    "model_id and model_selection disagree.",
                    {"model_id": legacy_model_id, "model_selection": model_selection},
                )
        if selection not in CATALOG:
            raise CatalogError(422, "MODEL_UNKNOWN", "Unknown model_selection.", {"known": sorted(CATALOG)})
    release = CATALOG[selection]
    if profile_id is None:
        profile = release.profiles[0]
    else:
        profile = release.profile(profile_id)
        if profile is None:
            raise CatalogError(
                422, "EXECUTION_PROFILE_UNKNOWN", "Unknown execution_profile_id for model.",
                {"model_selection": selection, "known": [p.profile_id for p in release.profiles]},
            )
        if profile.model_selection != selection:
            raise CatalogError(422, "EXECUTION_PROFILE_MISMATCH", "Profile does not belong to model.",
                               {"execution_profile_id": profile_id, "model_selection": selection})
    return release, profile


def _effective_nfe(resolved: dict[str, Any]) -> int:
    timesteps = resolved.get("timesteps")
    if isinstance(timesteps, str) and timesteps.strip():
        # A custom schedule's count is the real per-item evaluation budget.
        n = len([t for t in timesteps.split(",") if t.strip() != ""])
        if n:
            return n
    steps = int(resolved.get("inference_steps") or 0)
    infer_method = resolved.get("infer_method", "ode")
    # sde/heun-style 2nd-order sampling roughly doubles evaluations; approximate.
    return steps * (2 if infer_method == "sde" else 1)


def validate_profile_controls(profile: ExecutionProfile, controls: dict[str, Any]) -> dict[str, Any]:
    """Validate supplied controls against the profile, then fill omitted defaults.

    Validates first, fills second; never silently clamps an explicit value.
    Returns the resolved controls (OAL control names) or raises CatalogError
    (422 MODEL_PARAMETER_CONFLICT / CONTROL_UNSUPPORTED).
    """
    controls = dict(controls or {})

    # Sampler modes the pinned REST does not expose at all -> reject explicitly.
    if "sampler_mode" in controls:
        raise CatalogError(
            422, "MODEL_PARAMETER_CONFLICT",
            "sampler_mode is not supported by the pinned ACE-Step runtime.",
            {"control": "sampler_mode", "supported": ["infer_method"]},
        )

    # Keys this function interprets directly (not all live in CONTROL_SPECS).
    profile_managed = {
        "inference_steps", "guidance_scale", "dcw_enabled", "infer_method",
        "timesteps", "shift", "sampler_mode", "use_adg",
    }
    allowed = set(CONTROL_SPECS) | profile_managed
    unknown = sorted(set(controls) - allowed)
    if unknown:
        raise CatalogError(422, "CONTROL_UNSUPPORTED", "Unknown or unsupported controls supplied.",
                           {"unknown_controls": unknown, "supported_controls": sorted(allowed)})

    # Applicability: a control restricted to certain families must not be sent on
    # a release outside those families (e.g. base-only `shift` on Turbo).
    # `shift` is exempt: the ExecutionProfile owns its band/defaults per model
    # (turbo distills a discrete schedule, base/sft/merge use 1.0), so the
    # registry's base-only marker is not consulted here.
    for key in controls:
        if key == "shift":
            continue
        spec = CONTROL_SPECS.get(key)
        if spec is not None and spec.families is not None and profile.native_family not in spec.families:
            raise CatalogError(
                422, "CONTROL_UNSUPPORTED",
                f"{key} is not applicable to {profile.label} ({profile.native_family} models only).",
                {"control": key, "allowed_families": list(spec.families)},
            )

    # Steps.
    steps = controls.get("inference_steps", profile.steps_default)
    if not isinstance(steps, int) or isinstance(steps, bool):
        raise CatalogError(422, "MODEL_PARAMETER_CONFLICT", "inference_steps must be an integer.",
                           {"control": "inference_steps"})
    if profile.cfg_locked and steps != profile.steps_default:
        raise CatalogError(
            422, "MODEL_PARAMETER_CONFLICT",
            f"{profile.label} locks steps to {profile.steps_default}.",
            {"control": "inference_steps", "allowed": profile.steps_default},
        )
    if not profile.steps_min <= steps <= profile.steps_max:
        raise CatalogError(
            422, "MODEL_PARAMETER_CONFLICT",
            "inference_steps out of range for this model.",
            {"control": "inference_steps", "min": profile.steps_min, "max": profile.steps_max},
        )

    # CFG.
    cfg = controls.get("guidance_scale", profile.cfg_default)
    if not isinstance(cfg, (int, float)) or isinstance(cfg, bool):
        raise CatalogError(422, "MODEL_PARAMETER_CONFLICT", "guidance_scale must be numeric.", {"control": "guidance_scale"})
    cfg = float(cfg)
    if profile.cfg_locked and abs(cfg - profile.cfg_default) > 1e-6:
        raise CatalogError(
            422, "MODEL_PARAMETER_CONFLICT",
            f"{profile.label} uses a fixed effective CFG of {profile.cfg_default:g}.",
            {"control": "guidance_scale", "allowed": profile.cfg_default},
        )
    if not profile.cfg_min - 1e-6 <= cfg <= profile.cfg_max + 1e-6:
        raise CatalogError(422, "MODEL_PARAMETER_CONFLICT", "guidance_scale out of range for this model.",
                           {"control": "guidance_scale", "min": profile.cfg_min, "max": profile.cfg_max})

    # Shift (profile-owned band). Fills the default when omitted; non-turbo uses the
    # documented best-quality 3.0, turbo-family keeps its discrete-schedule 3.0.
    # Never clamps an explicit value.
    shift = controls.get("shift", profile.shift_default)
    if not isinstance(shift, (int, float)) or isinstance(shift, bool):
        raise CatalogError(422, "MODEL_PARAMETER_CONFLICT", "shift must be numeric.", {"control": "shift"})
    shift = float(shift)
    if not profile.shift_min - 1e-6 <= shift <= profile.shift_max + 1e-6:
        raise CatalogError(422, "MODEL_PARAMETER_CONFLICT", "shift out of range for this model.",
                           {"control": "shift", "min": profile.shift_min, "max": profile.shift_max})

    # Adaptive dual guidance (base/SFT quality; turbo ignores it). Profile default.
    use_adg = controls.get("use_adg", profile.adg_default)
    if not isinstance(use_adg, bool):
        raise CatalogError(422, "MODEL_PARAMETER_CONFLICT", "use_adg must be boolean.", {"control": "use_adg"})

    # DCW: safe SFT/XL profiles force it off; explicit non-False is a conflict.
    if "dcw_enabled" in controls and controls["dcw_enabled"] is not None:
        if not isinstance(controls["dcw_enabled"], bool):
            raise CatalogError(422, "MODEL_PARAMETER_CONFLICT", "dcw_enabled must be boolean.", {"control": "dcw_enabled"})
        if profile.dcw_forced_off and controls["dcw_enabled"] is not False:
            raise CatalogError(422, "MODEL_PARAMETER_CONFLICT", f"{profile.label} requires DCW off.",
                               {"control": "dcw_enabled", "required": False})

    resolved = {**{"inference_steps": steps, "guidance_scale": cfg, "shift": shift, "use_adg": use_adg}, **{k: v for k, v in controls.items() if k not in ("inference_steps", "guidance_scale", "shift", "use_adg")}}

    # Custom timesteps override steps (effective NFE must respect the budget).
    nfe = _effective_nfe(resolved)
    nfe_cap = profile.steps_max * (2 if resolved.get("infer_method") == "sde" else 1)
    if nfe > nfe_cap:
        raise CatalogError(
            422, "MODEL_PARAMETER_CONFLICT",
            "Requested sampler evaluations exceed this profile's compute budget.",
            {"effective_nfe": nfe, "max_nfe": nfe_cap},
        )
    return resolved


def base_charge(duration_seconds: int | None, takes: int) -> int:
    # Existing billing unit: one base charge per take (duration-banded pricing
    # can extend this later). Turbo multiplier 1.0 keeps the current amount.
    from .config import get_settings

    return get_settings().credit_cost_per_generation * max(1, min(4, takes))


def quoted_credits(profile: ExecutionProfile, takes: int, compute_factor: float | None = None) -> int:
    factor = profile.compute_factor if compute_factor is None else compute_factor
    from .config import get_settings

    base = get_settings().credit_cost_per_generation * max(1, min(4, takes))
    return math.ceil(base * profile.multiplier * max(1.0, factor))
