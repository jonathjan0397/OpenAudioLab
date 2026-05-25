from agent_app.config import AGENT_VERSION


def get_version() -> str:
    return AGENT_VERSION


def check_update_available(latest_version: str) -> bool:
    return AGENT_VERSION != latest_version
