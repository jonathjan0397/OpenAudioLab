from datetime import datetime, timezone

from app.db.models import GenerationJob, StorageAsset
from app.db.session import SessionLocal
from app.storage.service import StorageService


class RetentionCleanup:
    @staticmethod
    def cleanup_expired_jobs() -> int:
        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            expired_jobs = db.query(GenerationJob).filter(
                GenerationJob.expires_at <= now,
                GenerationJob.status.notin_(["expired", "cancelled"]),
            ).all()

            count = 0
            for job in expired_jobs:
                assets = db.query(StorageAsset).filter(StorageAsset.job_id == job.id).all()
                for asset in assets:
                    StorageService.delete_file(asset.storage_key)
                    asset.deleted_at = now

                job.status = "expired"
                job.updated_at = now
                count += 1

            if count > 0:
                db.commit()

            return count
        finally:
            db.close()

    @staticmethod
    def cleanup_failed_intermediates() -> int:
        db = SessionLocal()
        try:
            from datetime import timedelta
            threshold = datetime.now(timezone.utc) - timedelta(hours=24)

            expired_assets = db.query(StorageAsset).filter(
                StorageAsset.asset_type == "failed_intermediate",
                StorageAsset.created_at <= threshold,
                StorageAsset.deleted_at.is_(None),
            ).all()

            count = 0
            for asset in expired_assets:
                StorageService.delete_file(asset.storage_key)
                asset.deleted_at = now
                count += 1

            if count > 0:
                db.commit()

            return count
        finally:
            db.close()
