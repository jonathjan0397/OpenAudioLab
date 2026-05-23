import logging
import signal
import sys
import threading
import time

from worker_app.config import (
    BACKEND_URL,
    MODEL_PACK_PATH,
    POLL_INTERVAL,
    WORKER_NAME,
    WORKER_REGISTRATION_TOKEN,
)
from worker_app.heartbeat import heartbeat_loop
from worker_app.job_runner import JobRunner
from worker_app.model_manifest import load_model_manifest
from worker_app.registration import register_worker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("worker.main")


def main():
    logger.info(f"OpenAudiolab Worker starting (name={WORKER_NAME})")
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

    registration = register_worker()
    if not registration.get("accepted"):
        logger.error("Worker registration failed. Exiting.")
        sys.exit(1)

    worker_id = registration.get("worker_id")
    worker_api_token = registration.get("worker_api_token")

    if not worker_id or not worker_api_token:
        logger.error("Registration did not return worker_id or worker_api_token")
        sys.exit(1)

    heartbeat_thread = threading.Thread(
        target=heartbeat_loop,
        args=(worker_id, worker_api_token, stop_event),
        daemon=True,
    )
    heartbeat_thread.start()

    runner = JobRunner(worker_id, worker_api_token)

    logger.info("Worker ready. Polling for jobs...")

    while not stop_event.is_set():
        job_response = runner.request_job()

        if job_response.get("job_available"):
            job_data = job_response.get("job", {})
            runner.run_job(job_data)
        else:
            stop_event.wait(POLL_INTERVAL)

    logger.info("Worker shutting down")


if __name__ == "__main__":
    main()
