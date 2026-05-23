from fastapi import APIRouter, Depends, HTTPException

from app.auth.dependencies import require_auth
from app.db.models import User
from app.storage.service import StorageService

router = APIRouter(prefix="/api/storage", tags=["storage"])


@router.get("/assets")
async def list_assets(current_user: User = Depends(require_auth)):
    from app.db.session import SessionLocal
    from app.db.models import StorageAsset

    db = SessionLocal()
    try:
        assets = db.query(StorageAsset).filter(StorageAsset.deleted_at.is_(None)).all()
        return [
            {
                "id": a.id,
                "job_id": a.job_id,
                "asset_type": a.asset_type,
                "filename": a.filename,
                "mime_type": a.mime_type,
                "size_bytes": a.size_bytes,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in assets
        ]
    finally:
        db.close()


@router.get("/download/{path:path}")
async def download_asset(path: str, expires: int = None, current_user: User = Depends(require_auth)):
    from urllib.parse import unquote

    remote_key = unquote(path)
    url = StorageService.generate_signed_url(remote_key)
    if url is None:
        raise HTTPException(status_code=404, detail="File not found")
    return {"download_url": url}
