from typing import Optional

from app.db.models import ModelRegistryEntry
from app.db.session import SessionLocal


class ModelRegistry:
    @staticmethod
    def register_model(
        model_id: str,
        display_name: str,
        engine: str,
        task: str,
        version: str,
        source_url: Optional[str] = None,
        license_name: Optional[str] = None,
        license_url: Optional[str] = None,
        redistributable_status: str = "needs_review",
        commercial_safe_status: str = "needs_review",
        capabilities: Optional[dict] = None,
        min_vram_gb: int = 0,
        recommended_vram_gb: int = 0,
        default_container_policy: str = "mounted",
        notes: Optional[str] = None,
    ) -> Optional[ModelRegistryEntry]:
        db = SessionLocal()
        try:
            existing = db.query(ModelRegistryEntry).filter(ModelRegistryEntry.model_id == model_id).first()
            if existing:
                return existing

            entry = ModelRegistryEntry(
                model_id=model_id,
                display_name=display_name,
                engine=engine,
                task=task,
                version=version,
                source_url=source_url,
                license=license_name,
                license_url=license_url,
                redistributable_status=redistributable_status,
                commercial_safe_status=commercial_safe_status,
                capabilities_json=capabilities,
                min_vram_gb=min_vram_gb,
                recommended_vram_gb=recommended_vram_gb,
                default_container_policy=default_container_policy,
                notes=notes,
            )
            db.add(entry)
            db.commit()
            db.refresh(entry)
            return entry
        finally:
            db.close()

    @staticmethod
    def get_model(model_id: str) -> Optional[ModelRegistryEntry]:
        db = SessionLocal()
        try:
            return db.query(ModelRegistryEntry).filter(ModelRegistryEntry.model_id == model_id).first()
        finally:
            db.close()

    @staticmethod
    def list_models() -> list[dict]:
        db = SessionLocal()
        try:
            models = db.query(ModelRegistryEntry).all()
            return [
                {
                    "model_id": m.model_id,
                    "display_name": m.display_name,
                    "engine": m.engine,
                    "task": m.task,
                    "version": m.version,
                    "license": m.license,
                    "redistributable_status": m.redistributable_status,
                    "commercial_safe_status": m.commercial_safe_status,
                    "min_vram_gb": m.min_vram_gb,
                    "recommended_vram_gb": m.recommended_vram_gb,
                }
                for m in models
            ]
        finally:
            db.close()
