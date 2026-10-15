"""Dispatcher process entry point: outbox publication and lease reconciliation."""

from __future__ import annotations

import logging

from .config import get_settings
from .db import Db
from .orchestration import Dispatcher
from .queue import RedisQueue


def build_dispatcher() -> Dispatcher:
    settings = get_settings()
    import redis

    db = Db(settings.database_url)
    queue = RedisQueue(redis.Redis.from_url(settings.redis_url))
    return Dispatcher(db, queue, settings)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        build_dispatcher().run_forever()
    except KeyboardInterrupt:
        pass
