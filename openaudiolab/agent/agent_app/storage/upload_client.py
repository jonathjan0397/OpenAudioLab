import os
import logging

import requests

from agent_app.config import BACKEND_URL

logger = logging.getLogger("agent.storage")


class StorageUploadClient:
    def __init__(self, agent_api_token: str):
        self.agent_api_token = agent_api_token

    def upload(self, local_path: str, remote_key: str) -> bool:
        if not os.path.exists(local_path):
            logger.warning(f"File not found: {local_path}")
            return False
        return True

    def upload_content(self, content: str, remote_key: str) -> bool:
        return True
