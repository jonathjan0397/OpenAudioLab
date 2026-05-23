import json
from typing import Optional

import redis

from app.core.config import settings


redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)

JOB_QUEUE_KEY = "openaudiolab:job_queue"
WORKER_QUEUE_KEY = "openaudiolab:worker_queue"


class JobQueue:
    @staticmethod
    def enqueue_job(job_id: str) -> bool:
        try:
            redis_client.lpush(JOB_QUEUE_KEY, job_id)
            return True
        except Exception:
            return False

    @staticmethod
    def dequeue_job() -> Optional[str]:
        try:
            result = redis_client.rpop(JOB_QUEUE_KEY)
            return result
        except Exception:
            return None

    @staticmethod
    def get_queue_length() -> int:
        try:
            return redis_client.llen(JOB_QUEUE_KEY)
        except Exception:
            return 0

    @staticmethod
    def peek_queue() -> list[str]:
        try:
            return redis_client.lrange(JOB_QUEUE_KEY, 0, -1)
        except Exception:
            return []

    @staticmethod
    def remove_job(job_id: str) -> bool:
        try:
            redis_client.lrem(JOB_QUEUE_KEY, 0, job_id)
            return True
        except Exception:
            return False


class WorkerQueue:
    @staticmethod
    def register_worker(worker_id: str) -> bool:
        try:
            redis_client.sadd(WORKER_QUEUE_KEY, worker_id)
            return True
        except Exception:
            return False

    @staticmethod
    def unregister_worker(worker_id: str) -> bool:
        try:
            redis_client.srem(WORKER_QUEUE_KEY, worker_id)
            return True
        except Exception:
            return False

    @staticmethod
    def get_available_workers() -> list[str]:
        try:
            return list(redis_client.smembers(WORKER_QUEUE_KEY))
        except Exception:
            return []
