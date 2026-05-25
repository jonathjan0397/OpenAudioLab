import logging

logger = logging.getLogger("worker.drain")


def check_drain_status() -> bool:
    return False


def start_drain():
    logger.info("Drain mode activated")


def stop_drain():
    logger.info("Drain mode deactivated")
