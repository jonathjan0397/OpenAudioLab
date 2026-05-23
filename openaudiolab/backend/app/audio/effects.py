from typing import Optional


class EffectsProcessor:
    SUPPORTED_EFFECTS = [
        "normalize",
        "gain",
        "fade",
        "limiter",
        "eq",
        "reverb",
    ]

    @staticmethod
    def apply_effect(input_path: str, effect_type: str, params: Optional[dict] = None) -> Optional[str]:
        return input_path

    @staticmethod
    def apply_chain(input_path: str, effects_chain: list[dict]) -> Optional[str]:
        current_path = input_path
        for effect in effects_chain:
            result = EffectsProcessor.apply_effect(
                current_path,
                effect.get("type", ""),
                effect.get("params"),
            )
            if result:
                current_path = result
        return current_path

    @staticmethod
    def build_default_chain(preset: str = "demo_draft") -> list[dict]:
        chains = {
            "demo_draft": [
                {"type": "normalize", "params": {"target_db": -1.0}},
                {"type": "gain", "params": {"gain_db": 0.0}},
            ],
            "streaming_balanced": [
                {"type": "normalize", "params": {"target_db": -1.0}},
                {"type": "eq", "params": {"preset": "streaming"}},
                {"type": "limiter", "params": {"threshold_db": -1.0}},
            ],
            "loud_modern": [
                {"type": "normalize", "params": {"target_db": -0.5}},
                {"type": "eq", "params": {"preset": "modern"}},
                {"type": "limiter", "params": {"threshold_db": -0.5}},
            ],
            "warm_analog": [
                {"type": "normalize", "params": {"target_db": -1.0}},
                {"type": "eq", "params": {"preset": "warm"}},
                {"type": "reverb", "params": {"mix": 0.1}},
            ],
            "club_master": [
                {"type": "normalize", "params": {"target_db": -0.3}},
                {"type": "eq", "params": {"preset": "club"}},
                {"type": "limiter", "params": {"threshold_db": -0.3}},
            ],
        }
        return chains.get(preset, chains["demo_draft"])
