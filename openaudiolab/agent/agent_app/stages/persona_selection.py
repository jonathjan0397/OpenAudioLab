import logging

logger = logging.getLogger("agent.stages.persona_selection")

PERSONAS = {
    "male": {
        "display": "Male Vocal",
        "type": "singer",
        "range": "baritone/tenor",
        "default_model": "voice-male-v1",
    },
    "female": {
        "display": "Female Vocal",
        "type": "singer",
        "range": "alto/soprano",
        "default_model": "voice-female-v1",
    },
    "robotic": {
        "display": "Robotic / TTS",
        "type": "synthesized",
        "default_model": "tts-default-v1",
    },
    "spoken_word": {
        "display": "Spoken Word",
        "type": "narration",
        "default_model": "voice-spoken-v1",
    },
    "instrumental_only": {
        "display": "Instrumental (No Vocals)",
        "type": "instrumental",
        "default_model": None,
    },
}


def select(request: dict) -> dict:
    vocal_mode = request.get("vocal_mode", "male")
    instrumental = request.get("instrumental", False)

    if instrumental:
        persona = PERSONAS["instrumental_only"]
        return {
            "selected": "instrumental_only",
            "type": "instrumental",
            "display": persona["display"],
            "vocal_mode": "none",
        }

    persona = PERSONAS.get(vocal_mode, PERSONAS["male"])
    result = {
        "selected": vocal_mode,
        "type": persona["type"],
        "display": persona["display"],
        "range": persona["range"],
        "default_model": persona["default_model"],
        "vocal_mode": vocal_mode,
    }

    logger.info("Selected persona: %s (%s)", result["display"], vocal_mode)
    return result