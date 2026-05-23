import logging
import time

import requests

from worker_app.config import BACKEND_URL, WORKER_NAME, WORKER_MODE, WORKER_REGISTRATION_TOKEN, WORKER_VERSION
from worker_app.gpu_detect import detect_gpu

logger = logging.getLogger("worker.registration")


def register_worker() -> dict:
    gpu_info = detect_gpu()

    payload = {
        "worker_name": WORKER_NAME,
        "worker_mode": WORKER_MODE,
        "hostname": WORKER_NAME,
        "registration_token": WORKER_REGISTRATION_TOKEN,
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
        "container_version": WORKER_VERSION,
    }

    for attempt in range(5):
        try:
            response = requests.post(
                f"{BACKEND_URL}/api/workers/register",
                json=payload,
                timeout=10,
            )
            if response.status_code == 200:
                result = response.json()
                logger.info(f"Worker registered: {result.get('worker_id')}")
                return result
            logger.warning(f"Registration attempt {attempt + 1} failed: {response.status_code}")
        except Exception as e:
            logger.warning(f"Registration attempt {attempt + 1} error: {e}")

        time.sleep(5)

    logger.error("Failed to register worker after 5 attempts")
    return {}
