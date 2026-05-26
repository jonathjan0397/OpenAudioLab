import logging
import mimetypes
import os

import requests

from agent_app.config import BACKEND_URL

logger = logging.getLogger("agent.storage")


class StorageUploadClient:
    def __init__(self, agent_api_token: str):
        self.agent_api_token = agent_api_token

    def upload(self, local_path: str, remote_key: str, asset_type: str = "export_zip") -> bool:
        if not os.path.exists(local_path):
            logger.warning("File not found: %s", local_path)
            return False

        job_id = self._extract_job_id(remote_key)
        if not job_id:
            logger.warning("Could not extract job_id from remote_key: %s", remote_key)
            return False

        filename = os.path.basename(local_path)
        try:
            with open(local_path, "rb") as f:
                files = {"file": (filename, f, mimetypes.guess_type(filename)[0] or "application/octet-stream")}
                data = {"asset_type": asset_type, "filename": filename}
                resp = requests.post(
                    f"{BACKEND_URL}/api/agents/jobs/{job_id}/artifacts",
                    files=files,
                    data=data,
                    headers={"X-Agent-Token": self.agent_api_token},
                    timeout=300,
                )
            if resp.status_code == 200:
                result = resp.json()
                logger.info("Uploaded %s → %s (asset_id=%s)", filename, remote_key, result.get("asset_id"))
                return True
            logger.warning("Upload failed for %s: %s %s", filename, resp.status_code, resp.text)
            return False
        except Exception as e:
            logger.error("Upload error for %s: %s", filename, e)
            return False

    def upload_content(self, content: str, remote_key: str, asset_type: str = "metadata") -> bool:
        import tempfile

        filename = os.path.basename(remote_key) or "content.txt"
        tmp = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=filename, encoding="utf-8")
        try:
            tmp.write(content)
            tmp.close()
            return self.upload(tmp.name, remote_key, asset_type=asset_type)
        finally:
            os.unlink(tmp.name)

    @staticmethod
    def _extract_job_id(remote_key: str) -> str | None:
        parts = remote_key.lstrip("/").split("/")
        if len(parts) >= 2 and parts[0] == "jobs":
            return parts[1]
        return None