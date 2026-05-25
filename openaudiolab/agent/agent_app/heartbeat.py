import logging
import time

import requests

from agent_app.config import BACKEND_URL, HEARTBEAT_INTERVAL, AGENT_VERSION

logger = logging.getLogger("agent.heartbeat")


def send_heartbeat(agent_id: str, agent_api_token: str, status: str = "idle", active_job_id: str = None, draining: bool = False) -> dict:
    payload = {
        "agent_id": agent_id,
        "status": status,
        "active_job_id": active_job_id,
        "container_version": AGENT_VERSION,
        "draining": draining,
    }

    try:
        response = requests.post(
            f"{BACKEND_URL}/api/agents/heartbeat",
            json=payload,
            headers={"X-Agent-Token": agent_api_token},
            timeout=10,
        )
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        logger.warning(f"Heartbeat error: {e}")

    return {"accepted": False}


def heartbeat_loop(agent_id: str, agent_api_token: str, stop_event):
    logger.info(f"Starting heartbeat loop (interval={HEARTBEAT_INTERVAL}s)")
    while not stop_event.is_set():
        result = send_heartbeat(agent_id, agent_api_token)
        if result.get("drain_requested"):
            logger.info("Drain requested by backend")
        if result.get("update_required"):
            logger.warning("Update required by backend")
        stop_event.wait(HEARTBEAT_INTERVAL)
