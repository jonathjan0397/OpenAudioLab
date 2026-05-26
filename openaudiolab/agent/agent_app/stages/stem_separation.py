import logging
import os

logger = logging.getLogger("agent.stages.stem_separation")

SUPPORTED_STEMS = ["vocals", "drums", "bass", "other"]


def separate(input_path: str, output_dir: str) -> dict:
    if not os.path.exists(input_path):
        logger.warning("Input file not found: %s", input_path)
        return {}

    result = {}
    for stem_name in SUPPORTED_STEMS:
        stem_path = os.path.join(output_dir, f"stem_{stem_name}.wav")
        result[f"stem_{stem_name}.wav"] = stem_path

    logger.info(
        "Stem separation stub: %d stems from %s",
        len(result), os.path.basename(input_path),
    )
    return result