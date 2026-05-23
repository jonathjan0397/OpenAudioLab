from typing import Optional

from app.db.models import WorkerNode
from app.db.session import SessionLocal


class WorkerRegistry:
    @staticmethod
    def get_worker_by_id(worker_id: str) -> Optional[WorkerNode]:
        db = SessionLocal()
        try:
            return db.query(WorkerNode).filter(WorkerNode.id == worker_id).first()
        finally:
            db.close()

    @staticmethod
    def get_worker_by_token(worker_api_token: str) -> Optional[WorkerNode]:
        db = SessionLocal()
        try:
            return db.query(WorkerNode).filter(WorkerNode.worker_api_token == worker_api_token).first()
        finally:
            db.close()

    @staticmethod
    def get_available_workers() -> list[WorkerNode]:
        db = SessionLocal()
        try:
            return db.query(WorkerNode).filter(
                WorkerNode.status == "idle",
                WorkerNode.draining == False,
            ).all()
        finally:
            db.close()

    @staticmethod
    def get_workers_with_capability(capability: str) -> list[WorkerNode]:
        db = SessionLocal()
        try:
            workers = db.query(WorkerNode).filter(
                WorkerNode.status == "idle",
                WorkerNode.draining == False,
            ).all()
            result = []
            for w in workers:
                caps = w.capabilities_json or {}
                if caps.get(capability, False):
                    result.append(w)
            return result
        finally:
            db.close()
