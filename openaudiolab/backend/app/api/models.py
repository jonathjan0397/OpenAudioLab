from fastapi import APIRouter

from app.models.registry import ModelRegistry

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("")
async def list_models():
    return ModelRegistry.list_models()
