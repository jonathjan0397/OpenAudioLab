import logging
import time

import requests

from agent_app.config import BACKEND_URL, AGENT_NAME, AGENT_MODE, AGENT_REGISTRATION_TOKEN, AGENT_VERSION
from agent_app.gpu_detect import detect_gpu

logger = logging.getLogger("agent.registration")


def register_agent() -> dict:
    gpu_info = detect_gpu()

    payload = {
        "agent_name": AGENT_NAME,
        "agent_mode": AGENT_MODE,
        "hostname": AGENT_NAME,
        "registration_token": AGENT_REGISTRATION_TOKEN,
        "gpu": gpu_info,
        "capabilities": {
            "lyrics": True,
            "lyrics_reasoning": True,
            "music_generation": gpu_info.get("available", False),
            "cpu_test_generation": True,
            "daw_processing": True,
            "effects": True,
            "mastering": True,
            "zip_export": True,
        },
        "model_packs": ["model-pack-lite"],
        "container_version": AGENT_VERSION,
    }

    for attempt in range(5):
        try:
            response = requests.post(
                f"{BACKEND_URL}/api/agents/register",
                json=payload,
                timeout=10,
            )
            if response.status_code == 200:
                result = response.json()
                logger.info(f"Agent registered: {result.get('agent_id')}")
                return result
            logger.warning(f"Registration attempt {attempt + 1} failed: {response.status_code}")
        except Exception as e:
            logger.warning(f"Registration attempt {attempt + 1} error: {e}")

        time.sleep(5)

    logger.error("Failed to register agent after 5 attempts")
    return {}
