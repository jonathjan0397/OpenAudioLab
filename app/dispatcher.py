"""Dispatcher process entry point: outbox publication and lease reconciliation."""

from __future__ import annotations

import logging

from .config import get_settings
from .db import Db
from .orchestration import Dispatcher
from .queue import RedisQueue, build_redis


def build_dispatcher() -> Dispatcher:
    settings = get_settings()
    db = Db(settings.database_url)
    queue = RedisQueue(build_redis(settings.redis_url))
    return Dispatcher(db, queue, settings)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        build_dispatcher().run_forever()
    except KeyboardInterrupt:
        pass
