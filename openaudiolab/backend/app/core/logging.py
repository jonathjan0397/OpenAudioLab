import logging
import sys
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        import json

        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)

        if hasattr(record, "job_id"):
            log_entry["job_id"] = record.job_id
        if hasattr(record, "stage"):
            log_entry["stage"] = record.stage
        if hasattr(record, "worker_id"):
            log_entry["worker_id"] = record.worker_id

        extra_fields = {
            k: v for k, v in record.__dict__.items()
            if k not in logging.LogRecord.__dict__ and k not in ("job_id", "stage", "worker_id")
        }
        if extra_fields:
            log_entry["extra"] = extra_fields

        return json.dumps(log_entry)


def setup_logging() -> None:
    log_level = logging.DEBUG if not settings.is_production else logging.INFO

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)

    if settings.is_production:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))

    root_logger.addHandler(handler)

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.LoggerAdapter:
    logger = logging.getLogger(name)
    return logger


logger = get_logger("openaudiolab")
