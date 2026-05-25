import logging
import os
import tempfile
import time

import requests

from agent_app.config import BACKEND_URL, CPU_TEST_MAX_DURATION_SECONDS, ENABLE_CPU_TEST_GENERATION
from agent_app.pipeline_runner import PipelineRunner

logger = logging.getLogger("agent.job_runner")


class JobRunner:
    def __init__(self, agent_id: str, agent_api_token: str):
        self.agent_id = agent_id
        self.agent_api_token = agent_api_token
        self.current_job_id = None

    def request_job(self) -> dict:
        try:
            response = requests.post(
                f"{BACKEND_URL}/api/agents/request-job",
                params={"agent_id": self.agent_id},
                headers={"X-Agent-Token": self.agent_api_token},
                timeout=30,
            )
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logger.warning(f"Job request error: {e}")
        return {"job_available": False}

    def run_job(self, job_data: dict) -> bool:
        job_id = job_data["job_id"]
        self.current_job_id = job_id
        logger.info(f"Starting job {job_id}")

        try:
            self._update_stage(job_id, "job_intake", "running")
            time.sleep(0.5)
            self._update_stage(job_id, "job_intake", "completed")

            runner = PipelineRunner(job_id, job_data.get("request", {}), self.agent_api_token)
            result = runner.run()

            if result:
                self._complete_job(job_id)
                logger.info(f"Job {job_id} completed successfully")
                return True
            else:
                self._fail_job(job_id, "Pipeline execution failed")
                logger.error(f"Job {job_id} failed")
                return False

        except Exception as e:
            self._fail_job(job_id, str(e))
            logger.error(f"Job {job_id} error: {e}")
            return False
        finally:
            self.current_job_id = None

    def _update_stage(self, job_id: str, stage_name: str, status: str, metadata: dict = None):
        try:
            requests.post(
                f"{BACKEND_URL}/api/agents/jobs/{job_id}/stage-update",
                json={"stage_name": stage_name, "status": status, "metadata": metadata},
                headers={"X-Agent-Token": self.agent_api_token},
                timeout=10,
            )
        except Exception:
            pass

    def _complete_job(self, job_id: str):
        try:
            requests.post(
                f"{BACKEND_URL}/api/agents/jobs/{job_id}/complete",
                headers={"X-Agent-Token": self.agent_api_token},
                timeout=10,
            )
        except Exception:
            pass

    def _fail_job(self, job_id: str, error: str):
        try:
            requests.post(
                f"{BACKEND_URL}/api/agents/jobs/{job_id}/fail",
                params={"error_message": error},
                headers={"X-Agent-Token": self.agent_api_token},
                timeout=10,
            )
        except Exception:
            pass
