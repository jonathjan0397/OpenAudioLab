"""Redis delivery hints. The database remains the authoritative job truth.

Chosen queue mechanism (milestone-0 decision, documented here): plain Redis
lists (LPUSH + BRPOP) with database-coordinated claims. At-least-once delivery;
duplicate messages are harmless because claims are guarded by job state and
attempt uniqueness in PostgreSQL. No queue library dependency is required for
this contract, and remote Vast.ai workers will use the same primitive over a
TLS-secured Redis.
"""

from __future__ import annotations

from typing import Any


def build_redis(url: str) -> Any:
    """Blocking-safe Redis client.

    redis-py >=6 defaults socket_timeout to 5 s, which races BRPOP blocking
    reads; blocking workers need the socket to outlive the server-side timeout.
    """
    import redis

    return redis.Redis.from_url(url, socket_timeout=None, health_check_interval=30)


class RedisQueue:
    def __init__(self, client: Any) -> None:
        self.client = client

    @staticmethod
    def queue_name(model_id: str) -> str:
        return f"oal:queue:{model_id}"

    @staticmethod
    def burst_name(queue: str) -> str:
        """Overflow tier consumed only by burst (Vast) workers."""
        return f"{queue}:burst"

    def publish(self, queue: str, job_id: str) -> None:
        self.client.lpush(queue, job_id)

    def receive(self, queue: str | list[str], timeout_seconds: int) -> str | None:
        item = self.client.brpop(queue, timeout=timeout_seconds)
        if item is None:
            return None
        if isinstance(item, (list, tuple)):
            item = item[-1]
        if isinstance(item, bytes):
            return item.decode("utf-8")
        return str(item)

    def depth(self, queue: str) -> int:
        return int(self.client.llen(queue))

    def peek(self, queue: str, count: int) -> list[str]:
        """Non-blocking window of the NEXT items BRPOP would consume.

        LPUSH+BRPOP is FIFO: the head of the *list* is the newest item, so the
        consumption window is the list TAIL (LRANGE -count..-1)."""
        items = self.client.lrange(queue, -count, -1)
        out = []
        for item in items:
            if isinstance(item, bytes):
                item = item.decode("utf-8")
            out.append(str(item))
        return out

    def remove(self, queue: str, job_id: str) -> int:
        """LREM one occurrence after a successful DB claim (Redis is a hint)."""
        return int(self.client.lrem(queue, 1, job_id))
