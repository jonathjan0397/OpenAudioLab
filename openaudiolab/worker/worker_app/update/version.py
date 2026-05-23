from worker_app.config import WORKER_VERSION


def get_version() -> str:
    return WORKER_VERSION


def check_update_available(latest_version: str) -> bool:
    return WORKER_VERSION != latest_version
