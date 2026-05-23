from datetime import datetime, timedelta, timezone

from app.db.models import WorkerNode
from app.db.session import SessionLocal

HEARTBEAT_TIMEOUT_MINUTES = 5


class HeartbeatMonitor:
    @staticmethod
    def check_stale_workers() -> list[str]:
        db = SessionLocal()
        try:
            threshold = datetime.now(timezone.utc) - timedelta(minutes=HEARTBEAT_TIMEOUT_MINUTES)
            stale_workers = db.query(WorkerNode).filter(
                WorkerNode.status != "offline",
                WorkerNode.last_heartbeat_at < threshold,
            ).all()

            stale_ids = []
            for worker in stale_workers:
                worker.status = "offline"
                stale_ids.append(worker.id)

            if stale_ids:
                db.commit()

            return stale_ids
        finally:
            db.close()

    @staticmethod
    def is_worker_alive(worker_id: str) -> bool:
        db = SessionLocal()
        try:
            worker = db.query(WorkerNode).filter(WorkerNode.id == worker_id).first()
            if not worker:
                return False
            if not worker.last_heartbeat_at:
                return False
            threshold = datetime.now(timezone.utc) - timedelta(minutes=HEARTBEAT_TIMEOUT_MINUTES)
            return worker.last_heartbeat_at >= threshold
        finally:
            db.close()
