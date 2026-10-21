"""Model voice capability manifests (UAIS).

Machine-readable, per-checkpoint voice/adapter capabilities for the installed
ACE-Step runtime (upstream pin ``ca1e85f``). Compatibility is determined by
these records plus validation results -- never by model-name similarity.
Values marked unverified stay unverified until a controlled test on the actual
runtime + hardware passes; nothing here is inferred from another variant.
"""

from __future__ import annotations

from dataclasses import dataclass, field

RUNTIME_REVISION = "1.5.0@ca1e85f"
LORA_RECIPE = "acestep-lora@ca1e85f"


@dataclass(frozen=True)
class ModelVoiceCapability:
    model_selection: str
    engine_model: str
    param_class: str                     # "2b" | "4b"
    base_revision: str                   # installed runtime pin
    adapter_format: str | None           # "peft_lora" when the runtime loads it
    adapter_load_verified: bool          # controlled loading test passed here
    training_recipe: str | None          # headless LoRA recipe; None => no path
    reference_conditioning: str | None   # mechanism for reference audio, if any
    reference_identity_verified: bool    # vocal-identity preservation demonstrated
    vram_train_mb: int | None
    vram_train_basis: str                # measured | estimated | unverified
    limitations: tuple[str, ...] = field(default_factory=tuple)

    def manifest(self) -> dict:
        return {
            "model_selection": self.model_selection,
            "engine_model": self.engine_model,
            "param_class": self.param_class,
            "base_revision": self.base_revision,
            "adapter_format": self.adapter_format,
            "adapter_load_verified": self.adapter_load_verified,
            "training_recipe": self.training_recipe,
            "reference_conditioning": self.reference_conditioning,
            "reference_identity_verified": self.reference_identity_verified,
            "vram_train_mb": self.vram_train_mb,
            "vram_train_basis": self.vram_train_basis,
            "limitations": list(self.limitations),
        }


_XL_LIMITS = (
    "2B LoRA weights are not compatible with the 4B XL DiT (tensor shapes differ)",
    "XL adapter loading not yet verified on the installed runtime",
    "XL training VRAM unverified on 24 GB workers (benchmark pending)",
)

VOICE_CAPABILITIES: dict[str, ModelVoiceCapability] = {
    c.model_selection: c
    for c in (
        ModelVoiceCapability(
            model_selection="ace-step-1.5-turbo",
            engine_model="acestep-v15-turbo",
            param_class="2b",
            base_revision=RUNTIME_REVISION,
            adapter_format="peft_lora",
            adapter_load_verified=True,   # real train/export/load cycles on this runtime
            training_recipe=LORA_RECIPE,
            reference_conditioning="cover-task",
            reference_identity_verified=False,
            vram_train_mb=12000,
            vram_train_basis="measured",  # house + in-app 2B LoRA runs on 24 GB cards
        ),
        ModelVoiceCapability(
            model_selection="ace-step-1.5-sft",
            engine_model="acestep-v15-sft",
            param_class="2b",
            base_revision=RUNTIME_REVISION,
            adapter_format="peft_lora",
            adapter_load_verified=False,  # same param class, but not load-tested
            training_recipe=LORA_RECIPE,
            reference_conditioning="cover-task",
            reference_identity_verified=False,
            vram_train_mb=12000,
            vram_train_basis="estimated",
            limitations=("2B Turbo adapter reuse on SFT requires a passing loading test",),
        ),
        ModelVoiceCapability(
            model_selection="ace-step-1.5-xl-turbo",
            engine_model="acestep-v15-xl-turbo",
            param_class="4b",
            base_revision=RUNTIME_REVISION,
            adapter_format="peft_lora",
            adapter_load_verified=False,
            training_recipe=LORA_RECIPE,
            reference_conditioning="cover-task",
            reference_identity_verified=False,
            vram_train_mb=None,
            vram_train_basis="unverified",
            limitations=_XL_LIMITS,
        ),
        ModelVoiceCapability(
            model_selection="ace-step-1.5-xl-sft",
            engine_model="acestep-v15-xl-sft",
            param_class="4b",
            base_revision=RUNTIME_REVISION,
            adapter_format="peft_lora",
            adapter_load_verified=False,
            training_recipe=LORA_RECIPE,
            reference_conditioning="cover-task",
            reference_identity_verified=False,
            vram_train_mb=None,
            vram_train_basis="unverified",
            limitations=_XL_LIMITS,
        ),
        ModelVoiceCapability(
            model_selection="ace-step-1.5-merge-sft-turbo",
            engine_model="acestep-v15-house-turbo",
            param_class="2b",
            base_revision=RUNTIME_REVISION,
            adapter_format="peft_lora",
            adapter_load_verified=False,
            training_recipe=LORA_RECIPE,
            reference_conditioning="cover-task",
            reference_identity_verified=False,
            vram_train_mb=12000,
            vram_train_basis="estimated",
            limitations=("Experimental merged checkpoint; adapter loading unverified",),
        ),
    )
}


def capability(model_selection: str) -> ModelVoiceCapability | None:
    return VOICE_CAPABILITIES.get(model_selection)
