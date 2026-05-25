import logging
import signal
import sys
import threading
import time

from agent_app.config import (
    BACKEND_URL,
    MODEL_PACK_PATH,
    POLL_INTERVAL,
    AGENT_NAME,
    AGENT_REGISTRATION_TOKEN,
)
from agent_app.heartbeat import heartbeat_loop
from agent_app.job_runner import JobRunner
from agent_app.model_manifest import load_model_manifest
from agent_app.registration import register_agent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("agent.main")


def main():
    logger.info(f"OpenAudiolab Agent starting (name={AGENT_NAME})")
    logger.info(f"Backend URL: {BACKEND_URL}")
    logger.info(f"Model pack: {MODEL_PACK_PATH}")

    manifest = load_model_manifest(MODEL_PACK_PATH)
    if manifest:
        logger.info(f"Loaded model pack: {manifest.get('display_name', 'unknown')}")

    stop_event = threading.Event()

    def signal_handler(sig, frame):
        logger.info("Shutdown signal received")
        stop_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    registration = register_agent()
    if not registration.get("accepted"):
        logger.error("Agent registration failed. Exiting.")
        sys.exit(1)

    agent_id = registration.get("agent_id")
    agent_api_token = registration.get("agent_api_token")

    if not agent_id or not agent_api_token:
        logger.error("Registration did not return agent_id or agent_api_token")
        sys.exit(1)

    heartbeat_thread = threading.Thread(
        target=heartbeat_loop,
        args=(agent_id, agent_api_token, stop_event),
        daemon=True,
    )
    heartbeat_thread.start()

    runner = JobRunner(agent_id, agent_api_token)

    logger.info("Agent ready. Polling for jobs...")

    while not stop_event.is_set():
        job_response = runner.request_job()

        if job_response.get("job_available"):
            job_data = job_response.get("job", {})
            runner.run_job(job_data)
        else:
            stop_event.wait(POLL_INTERVAL)

    logger.info("Agent shutting down")


if __name__ == "__main__":
    main()
